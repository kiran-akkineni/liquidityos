"""
Dispute service — create, respond, add evidence, resolve disputes.
Handles escrow holds, refund processing, and reputation impacts.
"""

from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event
from app.services.escrow import hold_escrow
from datetime import datetime, timezone, timedelta

SELLER_RESPONSE_DEADLINE_HOURS = 72
RESOLUTION_DEADLINE_HOURS = 168  # 7 days


def create_dispute(buyer_id: str, data: dict) -> dict:
    """Buyer files a dispute on a delivered order."""
    order_id = data["order_id"]

    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not order_row:
        return {"error": "ORDER_NOT_FOUND"}
    order = dict_from_row(order_row)

    if order["buyer_id"] != buyer_id:
        return {"error": "NOT_AUTHORIZED"}
    if order["status"] not in ("INSPECTION", "COMPLETED", "DELIVERED"):
        return {"error": "ORDER_NOT_DISPUTABLE",
                "message": f"Order status {order['status']} does not allow disputes."}

    dispute_id = make_id("dsp_")
    ts = now_iso()
    seller_deadline = (datetime.now(timezone.utc) + timedelta(hours=SELLER_RESPONSE_DEADLINE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolution_deadline = (datetime.now(timezone.utc) + timedelta(hours=RESOLUTION_DEADLINE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence = data.get("evidence", [])

    with get_db() as conn:
        conn.execute(
            """INSERT INTO disputes
               (dispute_id, order_id, lot_id, buyer_id, seller_id, escrow_id,
                type, description, affected_units, total_units, claimed_amount_cents,
                buyer_evidence, status, status_history,
                seller_response_deadline, resolution_deadline,
                opened_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPENED', ?, ?, ?, ?, ?, ?)""",
            (
                dispute_id, order_id, order["lot_id"],
                buyer_id, order["seller_id"], order.get("escrow_id"),
                data["type"], data["description"],
                data.get("affected_units", 0), data.get("total_units", 0),
                data["claimed_amount_cents"], json_dumps(evidence),
                json_dumps([{"status": "OPENED", "at": ts}]),
                seller_deadline, resolution_deadline, ts, ts, ts,
            ),
        )

        # Update order status to DISPUTED
        order_history = order.get("status_history", [])
        if isinstance(order_history, str):
            import json
            order_history = json.loads(order_history)
        order_history.append({"status": "DISPUTED", "at": ts})

        conn.execute(
            """UPDATE orders
               SET status = 'DISPUTED', inspection_result = 'DISPUTED',
                   inspection_result_at = ?, inspection_result_method = 'dispute_filed',
                   disputes = ?, status_history = ?, updated_at = ?
               WHERE order_id = ?""",
            (ts, json_dumps([dispute_id]), json_dumps(order_history), ts, order_id),
        )

    # Place hold on escrow for disputed amount
    if order.get("escrow_id"):
        hold_escrow(order["escrow_id"], f"DISPUTE_{dispute_id}", data["claimed_amount_cents"])

    log_event("dispute", dispute_id, "DisputeOpened", "buyer", buyer_id,
              new_state={"order_id": order_id, "type": data["type"],
                         "claimed_amount_cents": data["claimed_amount_cents"]},
              service="dispute-service")

    # Record reputation event: dispute filed against seller
    _record_dispute_filed_reputation(order, dispute_id)

    return get_dispute(dispute_id)


def get_dispute(dispute_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM disputes WHERE dispute_id = ?", (dispute_id,)).fetchone()
    return dict_from_row(row) if row else None


def list_disputes(filters: dict = None) -> list:
    filters = filters or {}
    with get_db() as conn:
        if "order_id" in filters:
            rows = conn.execute("SELECT * FROM disputes WHERE order_id = ? ORDER BY created_at DESC",
                                (filters["order_id"],)).fetchall()
        elif "buyer_id" in filters:
            rows = conn.execute("SELECT * FROM disputes WHERE buyer_id = ? ORDER BY created_at DESC",
                                (filters["buyer_id"],)).fetchall()
        elif "seller_id" in filters:
            rows = conn.execute("SELECT * FROM disputes WHERE seller_id = ? ORDER BY created_at DESC",
                                (filters["seller_id"],)).fetchall()
        elif "status" in filters:
            rows = conn.execute("SELECT * FROM disputes WHERE status = ? ORDER BY created_at DESC",
                                (filters["status"],)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM disputes ORDER BY created_at DESC LIMIT 50").fetchall()
    return rows_to_dicts(rows)


def respond_to_dispute(dispute_id: str, seller_id: str, data: dict) -> dict:
    """Seller responds to a dispute with their position and evidence."""
    dispute = get_dispute(dispute_id)
    if not dispute:
        return {"error": "DISPUTE_NOT_FOUND"}
    if dispute["seller_id"] != seller_id:
        return {"error": "NOT_AUTHORIZED"}
    if dispute["status"] != "OPENED":
        return {"error": "DISPUTE_NOT_OPEN", "message": f"Dispute status is {dispute['status']}"}

    ts = now_iso()
    seller_response = {
        "message": data.get("message", ""),
        "evidence": data.get("evidence", []),
        "proposed_resolution": data.get("proposed_resolution"),
        "proposed_refund_cents": data.get("proposed_refund_cents", 0),
        "responded_at": ts,
    }

    history = dispute.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "SELLER_RESPONDED", "at": ts})

    with get_db() as conn:
        conn.execute(
            """UPDATE disputes
               SET status = 'SELLER_RESPONDED', seller_response = ?,
                   status_history = ?, updated_at = ?
               WHERE dispute_id = ?""",
            (json_dumps(seller_response), json_dumps(history), ts, dispute_id),
        )

    log_event("dispute", dispute_id, "SellerResponded", "seller", seller_id,
              new_state={"proposed_resolution": data.get("proposed_resolution"),
                         "proposed_refund_cents": data.get("proposed_refund_cents", 0)},
              service="dispute-service")

    return get_dispute(dispute_id)


def add_evidence(dispute_id: str, actor_id: str, actor_type: str, evidence_item: dict) -> dict:
    """Add evidence to a dispute (buyer or seller)."""
    dispute = get_dispute(dispute_id)
    if not dispute:
        return {"error": "DISPUTE_NOT_FOUND"}
    if dispute["status"] in ("RESOLVED", "CLOSED"):
        return {"error": "DISPUTE_CLOSED"}

    # Verify actor is buyer or seller on this dispute
    if actor_type == "buyer" and dispute["buyer_id"] != actor_id:
        return {"error": "NOT_AUTHORIZED"}
    if actor_type == "seller" and dispute["seller_id"] != actor_id:
        return {"error": "NOT_AUTHORIZED"}

    ts = now_iso()
    evidence_entry = {
        "submitted_by": actor_type,
        "actor_id": actor_id,
        "type": evidence_item.get("type", "document"),
        "url": evidence_item.get("url", ""),
        "description": evidence_item.get("description", ""),
        "submitted_at": ts,
    }

    buyer_evidence = dispute.get("buyer_evidence", [])
    if isinstance(buyer_evidence, str):
        import json
        buyer_evidence = json.loads(buyer_evidence)
    buyer_evidence.append(evidence_entry)

    with get_db() as conn:
        conn.execute(
            "UPDATE disputes SET buyer_evidence = ?, updated_at = ? WHERE dispute_id = ?",
            (json_dumps(buyer_evidence), ts, dispute_id),
        )

    log_event("dispute", dispute_id, "EvidenceAdded", actor_type, actor_id,
              new_state={"evidence_type": evidence_entry["type"],
                         "submitted_by": actor_type},
              service="dispute-service")

    return get_dispute(dispute_id)


def resolve_dispute(dispute_id: str, resolver_id: str, data: dict) -> dict:
    """Ops resolves a dispute. Processes refund and reputation impacts."""
    dispute = get_dispute(dispute_id)
    if not dispute:
        return {"error": "DISPUTE_NOT_FOUND"}
    if dispute["status"] in ("RESOLVED", "CLOSED"):
        return {"error": "DISPUTE_ALREADY_RESOLVED"}

    ts = now_iso()
    resolution_type = data["resolution_type"]
    refund_amount = data.get("refund_amount_cents", 0)
    reasoning = data["reasoning"]

    # Create resolution record
    resolution_id = make_id("res_")

    # Determine financial actions based on resolution type
    financial_actions = []
    if resolution_type in ("FULL_REFUND", "PARTIAL_REFUND"):
        if resolution_type == "FULL_REFUND":
            refund_amount = dispute["claimed_amount_cents"]
        financial_actions.append({
            "action": "refund",
            "amount_cents": refund_amount,
            "to": "buyer",
            "from_escrow": dispute.get("escrow_id"),
        })

    # Determine reputation impacts
    reputation_impacts = _compute_reputation_impacts(dispute, resolution_type)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO resolutions
               (resolution_id, dispute_id, order_id, resolved_by, resolver_user_id,
                resolution_type, refund_amount_cents, refund_to, reasoning,
                financial_actions, reputation_impacts, created_at)
               VALUES (?, ?, ?, 'ops', ?, ?, ?, 'buyer', ?, ?, ?, ?)""",
            (
                resolution_id, dispute_id, dispute["order_id"], resolver_id,
                resolution_type, refund_amount, reasoning,
                json_dumps(financial_actions), json_dumps(reputation_impacts), ts,
            ),
        )

        # Update dispute status
        history = dispute.get("status_history", [])
        if isinstance(history, str):
            import json
            history = json.loads(history)
        history.append({"status": "RESOLVED", "at": ts, "resolved_by": resolver_id})

        conn.execute(
            """UPDATE disputes
               SET status = 'RESOLVED', resolution_id = ?,
                   status_history = ?, resolved_at = ?, updated_at = ?
               WHERE dispute_id = ?""",
            (resolution_id, json_dumps(history), ts, ts, dispute_id),
        )

    # Process refund via escrow
    if financial_actions:
        _process_refund(dispute, refund_amount)

    # Apply reputation impacts
    _apply_reputation_impacts(dispute, resolution_type, reputation_impacts)

    log_event("dispute", dispute_id, "DisputeResolved", "ops", resolver_id,
              new_state={"resolution_type": resolution_type,
                         "refund_amount_cents": refund_amount,
                         "resolution_id": resolution_id},
              service="dispute-service")

    return {
        "dispute": get_dispute(dispute_id),
        "resolution": get_resolution(resolution_id),
    }


def get_resolution(resolution_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM resolutions WHERE resolution_id = ?", (resolution_id,)).fetchone()
    return dict_from_row(row) if row else None


def _compute_reputation_impacts(dispute: dict, resolution_type: str) -> list:
    """Compute reputation score changes based on resolution outcome."""
    impacts = []

    if resolution_type in ("FULL_REFUND", "PARTIAL_REFUND"):
        # Seller loses reputation (resolved against them)
        impacts.append({
            "entity_type": "seller",
            "entity_id": dispute["seller_id"],
            "event_type": "DISPUTE_RESOLVED_AGAINST",
            "delta": -3 if resolution_type == "FULL_REFUND" else -2,
        })
        # Buyer gains (resolved in their favor)
        impacts.append({
            "entity_type": "buyer",
            "entity_id": dispute["buyer_id"],
            "event_type": "DISPUTE_RESOLVED_FAVOR",
            "delta": 1,
        })
    elif resolution_type == "NO_REFUND":
        # Buyer filed invalid dispute — slight penalty
        impacts.append({
            "entity_type": "buyer",
            "entity_id": dispute["buyer_id"],
            "event_type": "DISPUTE_RESOLVED_AGAINST",
            "delta": -1,
        })
        # Seller vindicated
        impacts.append({
            "entity_type": "seller",
            "entity_id": dispute["seller_id"],
            "event_type": "DISPUTE_RESOLVED_FAVOR",
            "delta": 1,
        })

    return impacts


def _apply_reputation_impacts(dispute: dict, resolution_type: str, impacts: list):
    """Apply reputation score changes to buyer and seller."""
    ts = now_iso()

    for impact in impacts:
        entity_type = impact["entity_type"]
        entity_id = impact["entity_id"]
        delta = impact["delta"]

        table = "sellers" if entity_type == "seller" else "buyers"
        id_col = "seller_id" if entity_type == "seller" else "buyer_id"
        score_field = "quality_score" if entity_type == "seller" else "trust_score"

        with get_db() as conn:
            row = conn.execute(f"SELECT {score_field} FROM {table} WHERE {id_col} = ?", (entity_id,)).fetchone()
        score_before = row[score_field] if row else 50
        score_after = max(0, min(100, score_before + delta))

        rep_id = make_id("rep_")
        with get_db() as conn:
            conn.execute(
                """INSERT INTO reputation_events
                   (reputation_event_id, entity_type, entity_id, event_type,
                    order_id, dispute_id, score_before, score_delta, score_after,
                    details, scoring_model_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1', ?)""",
                (rep_id, entity_type, entity_id, impact["event_type"],
                 dispute["order_id"], dispute["dispute_id"],
                 score_before, delta, score_after,
                 json_dumps({"resolution_type": resolution_type,
                             "dispute_type": dispute["type"]}),
                 ts),
            )

            conn.execute(
                f"UPDATE {table} SET {score_field} = ?, updated_at = ? WHERE {id_col} = ?",
                (score_after, ts, entity_id),
            )

            # Update dispute rate on seller
            if entity_type == "seller":
                total_txns = conn.execute(
                    "SELECT total_transactions FROM sellers WHERE seller_id = ?", (entity_id,)
                ).fetchone()
                total = total_txns["total_transactions"] if total_txns else 1
                dispute_count = conn.execute(
                    "SELECT COUNT(*) as c FROM disputes WHERE seller_id = ?", (entity_id,)
                ).fetchone()["c"]
                dispute_rate = round((dispute_count / max(total, 1)) * 100, 2)
                conn.execute(
                    "UPDATE sellers SET dispute_rate_pct = ? WHERE seller_id = ?",
                    (dispute_rate, entity_id),
                )


def _process_refund(dispute: dict, refund_amount_cents: int):
    """Process a refund from escrow back to buyer."""
    escrow_id = dispute.get("escrow_id")
    if not escrow_id:
        return

    ts = now_iso()
    from app.services.escrow import get_escrow

    escrow = get_escrow(escrow_id)
    if not escrow:
        return

    # Update escrow with partial release info
    releases = escrow.get("releases", [])
    if isinstance(releases, str):
        import json
        releases = json.loads(releases)
    releases.append({
        "reason": f"REFUND_DISPUTE_{dispute['dispute_id']}",
        "amount_cents": refund_amount_cents,
        "to": "buyer",
        "at": ts,
    })

    remaining = escrow["total_cents"] - refund_amount_cents
    new_status = "REFUNDED" if remaining <= 0 else "PARTIALLY_RELEASED"

    history = escrow.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": new_status, "at": ts, "reason": "dispute_resolution"})

    with get_db() as conn:
        conn.execute(
            """UPDATE escrow_transactions
               SET status = ?, releases = ?, status_history = ?, updated_at = ?
               WHERE escrow_id = ?""",
            (new_status, json_dumps(releases), json_dumps(history), ts, escrow_id),
        )

    log_event("escrow", escrow_id, "EscrowRefundProcessed", "system", "system",
              new_state={"refund_amount_cents": refund_amount_cents,
                         "new_status": new_status,
                         "dispute_id": dispute["dispute_id"]},
              service="escrow-service")


def _record_dispute_filed_reputation(order: dict, dispute_id: str):
    """Record a DISPUTE_FILED reputation event against the seller."""
    ts = now_iso()
    seller_id = order["seller_id"]

    with get_db() as conn:
        row = conn.execute("SELECT quality_score FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    score_before = row["quality_score"] if row else 50
    # Filing a dispute itself has a small negative signal (-1) for the seller
    delta = -1
    score_after = max(0, score_before + delta)

    rep_id = make_id("rep_")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO reputation_events
               (reputation_event_id, entity_type, entity_id, event_type,
                order_id, dispute_id, score_before, score_delta, score_after,
                details, scoring_model_version, created_at)
               VALUES (?, 'seller', ?, 'DISPUTE_FILED', ?, ?, ?, ?, ?, ?, 'v1', ?)""",
            (rep_id, seller_id, order["order_id"], dispute_id,
             score_before, delta, score_after,
             json_dumps({"reason": "Dispute filed by buyer"}), ts),
        )

        conn.execute(
            "UPDATE sellers SET quality_score = ?, updated_at = ? WHERE seller_id = ?",
            (score_after, ts, seller_id),
        )
