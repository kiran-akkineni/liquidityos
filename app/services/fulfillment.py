"""
Fulfillment service — buyer inspection, auto-accept, payout initiation, reputation events.
Covers the post-delivery lifecycle of an order.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event
from app.services.escrow import release_escrow
from datetime import datetime, timezone, timedelta

INSPECTION_WINDOW_HOURS = 48
REPUTATION_DELTA_ORDER_COMPLETED = 2


def accept_inspection(order_id: str, buyer_id: str) -> dict:
    """Buyer accepts the delivered lot. Releases escrow and initiates payout."""
    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not order_row:
        return {"error": "ORDER_NOT_FOUND"}
    order = dict_from_row(order_row)

    if order["status"] != "INSPECTION":
        return {"error": "ORDER_NOT_IN_INSPECTION", "message": f"Order status is {order['status']}"}
    if order["buyer_id"] != buyer_id:
        return {"error": "NOT_AUTHORIZED"}

    ts = now_iso()

    # Update order: INSPECTION → COMPLETED
    history = order.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "COMPLETED", "at": ts})

    with get_db() as conn:
        conn.execute(
            """UPDATE orders
               SET status = 'COMPLETED', inspection_result = 'ACCEPTED',
                   inspection_result_at = ?, inspection_result_method = 'buyer_action',
                   status_history = ?, completed_at = ?, updated_at = ?
               WHERE order_id = ?""",
            (ts, json_dumps(history), ts, ts, order_id),
        )

        # Mark lot as SOLD
        conn.execute(
            "UPDATE lots SET status = 'SOLD', sold_at = ?, updated_at = ? WHERE lot_id = ?",
            (ts, ts, order["lot_id"]),
        )

    log_event("order", order_id, "InspectionAccepted", "buyer", buyer_id,
              old_state={"status": "INSPECTION"},
              new_state={"status": "COMPLETED", "inspection_result": "ACCEPTED"},
              service="fulfillment-service")

    # Release escrow
    if order.get("escrow_id"):
        release_escrow(order["escrow_id"], "INSPECTION_ACCEPTED")

    # Initiate payout
    payout = _initiate_payout(order)

    # Record reputation events (+2 for both sides)
    _record_completion_reputation(order)

    return {
        "order_status": "COMPLETED",
        "inspection_result": "ACCEPTED",
        "payout": payout,
    }


def auto_accept_expired_inspections() -> list:
    """Auto-accept orders where the 48h inspection window has passed. Call periodically."""
    ts = now_iso()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM orders
               WHERE status = 'INSPECTION'
               AND inspection_window_closes_at < ?
               AND inspection_result IS NULL""",
            (ts,),
        ).fetchall()

    results = []
    for row in rows:
        order = dict_from_row(row)
        result = _auto_accept(order)
        results.append(result)
    return results


def _auto_accept(order: dict) -> dict:
    """System auto-accepts an inspection after 48h timeout."""
    ts = now_iso()
    order_id = order["order_id"]

    history = order.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "COMPLETED", "at": ts, "method": "auto_accept_timeout"})

    with get_db() as conn:
        conn.execute(
            """UPDATE orders
               SET status = 'COMPLETED', inspection_result = 'ACCEPTED',
                   inspection_result_at = ?, inspection_result_method = 'auto_accept_48h',
                   status_history = ?, completed_at = ?, updated_at = ?
               WHERE order_id = ?""",
            (ts, json_dumps(history), ts, ts, order_id),
        )

        conn.execute(
            "UPDATE lots SET status = 'SOLD', sold_at = ?, updated_at = ? WHERE lot_id = ?",
            (ts, ts, order["lot_id"]),
        )

    log_event("order", order_id, "InspectionAutoAccepted", "system", "system",
              old_state={"status": "INSPECTION"},
              new_state={"status": "COMPLETED", "inspection_result": "ACCEPTED",
                         "method": "auto_accept_48h"},
              service="fulfillment-service")

    if order.get("escrow_id"):
        release_escrow(order["escrow_id"], "AUTO_ACCEPT_48H")

    payout = _initiate_payout(order)
    _record_completion_reputation(order)

    return {"order_id": order_id, "auto_accepted": True, "payout": payout}


def _initiate_payout(order: dict) -> dict:
    """Create a payout record for the seller."""
    payout_id = make_id("pay_")
    ts = now_iso()
    expected_arrival = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d")

    # Get seller payment info for last4
    with get_db() as conn:
        seller_row = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (order["seller_id"],)).fetchone()
    seller = dict_from_row(seller_row) if seller_row else {}
    payment_info = seller.get("payment_info", {})
    if isinstance(payment_info, str):
        import json
        payment_info = json.loads(payment_info)
    last4 = payment_info.get("account_last4", "0000")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO payouts
               (payout_id, escrow_id, order_id, seller_id,
                amount_cents, method, destination_account_last4,
                processor, processor_payout_id, status, status_history,
                expected_arrival_date, created_at)
               VALUES (?, ?, ?, ?, ?, 'ach', ?, 'stripe', ?, 'INITIATED', ?, ?, ?)""",
            (
                payout_id, order.get("escrow_id", ""), order["order_id"], order["seller_id"],
                order["seller_payout_cents"], last4,
                f"po_{make_id('')}",
                json_dumps([{"status": "INITIATED", "at": ts}]),
                expected_arrival, ts,
            ),
        )

    log_event("payout", payout_id, "PayoutInitiated", "system", "system",
              new_state={"order_id": order["order_id"], "seller_id": order["seller_id"],
                         "amount_cents": order["seller_payout_cents"],
                         "expected_arrival": expected_arrival},
              service="payout-service")

    return get_payout(payout_id)


def get_payout(payout_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM payouts WHERE payout_id = ?", (payout_id,)).fetchone()
    return dict_from_row(row) if row else None


def get_payout_by_order(order_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM payouts WHERE order_id = ?", (order_id,)).fetchone()
    return dict_from_row(row) if row else None


def _record_completion_reputation(order: dict):
    """Record +2 reputation for both buyer and seller on order completion."""
    ts = now_iso()

    for entity_type, entity_id, score_field in [
        ("seller", order["seller_id"], "quality_score"),
        ("buyer", order["buyer_id"], "trust_score"),
    ]:
        # Get current score
        table = "sellers" if entity_type == "seller" else "buyers"
        id_col = "seller_id" if entity_type == "seller" else "buyer_id"
        with get_db() as conn:
            row = conn.execute(f"SELECT {score_field} FROM {table} WHERE {id_col} = ?", (entity_id,)).fetchone()
        score_before = row[score_field] if row else 50
        score_after = min(100, score_before + REPUTATION_DELTA_ORDER_COMPLETED)

        rep_id = make_id("rep_")
        with get_db() as conn:
            conn.execute(
                """INSERT INTO reputation_events
                   (reputation_event_id, entity_type, entity_id, event_type, order_id,
                    score_before, score_delta, score_after, details,
                    scoring_model_version, created_at)
                   VALUES (?, ?, ?, 'ORDER_COMPLETED', ?, ?, ?, ?, ?, 'v1', ?)""",
                (rep_id, entity_type, entity_id, order["order_id"],
                 score_before, REPUTATION_DELTA_ORDER_COMPLETED, score_after,
                 json_dumps({"reason": "Successful order completion"}), ts),
            )

            # Update the entity's score and transaction count
            conn.execute(
                f"""UPDATE {table}
                    SET {score_field} = ?, total_transactions = total_transactions + 1,
                        total_gmv_cents = total_gmv_cents + ?, updated_at = ?
                    WHERE {id_col} = ?""",
                (score_after, order["lot_price_cents"], ts, entity_id),
            )

    log_event("order", order["order_id"], "ReputationUpdated", "system", "system",
              new_state={"seller_delta": f"+{REPUTATION_DELTA_ORDER_COMPLETED}",
                         "buyer_delta": f"+{REPUTATION_DELTA_ORDER_COMPLETED}"},
              service="reputation-service")
