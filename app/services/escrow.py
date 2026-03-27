"""
Escrow service — create, fund, void, hold, and release escrow transactions.
Escrow protects buyers by holding funds until delivery + inspection pass.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event
from datetime import datetime, timezone, timedelta

FUNDING_DEADLINE_HOURS = 24


def create_escrow(order: dict) -> dict:
    """Create an escrow transaction for a confirmed order.
    Called automatically when an order is created."""
    escrow_id = make_id("esc_")
    ts = now_iso()
    deadline = (datetime.now(timezone.utc) + timedelta(hours=FUNDING_DEADLINE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    total = (
        order["lot_price_cents"]
        + order["platform_fee_cents"]
        + order["freight_cost_cents"]
        + order["insurance_cents"]
    )

    with get_db() as conn:
        conn.execute(
            """INSERT INTO escrow_transactions
               (escrow_id, order_id, buyer_id, seller_id,
                lot_price_cents, platform_fee_cents, freight_cost_cents, insurance_cents,
                total_cents, status, status_history, funding_deadline, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_FUNDING', ?, ?, ?, ?)""",
            (
                escrow_id, order["order_id"], order["buyer_id"], order["seller_id"],
                order["lot_price_cents"], order["platform_fee_cents"],
                order["freight_cost_cents"], order["insurance_cents"],
                total, json_dumps([{"status": "PENDING_FUNDING", "at": ts}]),
                deadline, ts, ts,
            ),
        )

        # Link escrow to order
        conn.execute(
            "UPDATE orders SET escrow_id = ?, updated_at = ? WHERE order_id = ?",
            (escrow_id, ts, order["order_id"]),
        )

    log_event("escrow", escrow_id, "EscrowCreated", "system", "system",
              new_state={"order_id": order["order_id"], "total_cents": total,
                         "funding_deadline": deadline},
              service="escrow-service")

    return get_escrow(escrow_id)


def get_escrow(escrow_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM escrow_transactions WHERE escrow_id = ?", (escrow_id,)).fetchone()
    return dict_from_row(row) if row else None


def get_escrow_by_order(order_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM escrow_transactions WHERE order_id = ?", (order_id,)).fetchone()
    return dict_from_row(row) if row else None


def fund_escrow(order_id: str, buyer_id: str, funding_data: dict) -> dict:
    """Buyer funds the escrow. Transitions order to AWAITING_SHIPMENT."""
    escrow = get_escrow_by_order(order_id)
    if not escrow:
        return {"error": "ESCROW_NOT_FOUND"}
    if escrow["status"] != "PENDING_FUNDING":
        return {"error": "ESCROW_NOT_PENDING", "message": f"Escrow status is {escrow['status']}"}
    if escrow["buyer_id"] != buyer_id:
        return {"error": "NOT_AUTHORIZED"}

    # Check funding deadline
    deadline = datetime.strptime(escrow["funding_deadline"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > deadline:
        void_escrow(escrow["escrow_id"], "FUNDING_DEADLINE_EXPIRED")
        return {"error": "FUNDING_DEADLINE_EXPIRED", "message": "The 24-hour funding window has passed."}

    ts = now_iso()
    funding_method = funding_data.get("method", "card")
    funding_reference = funding_data.get("reference", f"pay_{make_id('')}")

    # Update escrow status
    history = escrow.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "FUNDED", "at": ts})

    with get_db() as conn:
        conn.execute(
            """UPDATE escrow_transactions
               SET status = 'FUNDED', status_history = ?,
                   funding_method = ?, funding_amount_cents = ?,
                   funding_reference = ?, funding_processor_txn_id = ?,
                   funded_at = ?, updated_at = ?
               WHERE escrow_id = ?""",
            (
                json_dumps(history), funding_method, escrow["total_cents"],
                funding_reference, funding_data.get("processor_txn_id", f"pi_{make_id('')}"),
                ts, ts, escrow["escrow_id"],
            ),
        )

        # Transition order: AWAITING_PAYMENT → AWAITING_SHIPMENT
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        order = dict_from_row(order_row)
        order_history = order.get("status_history", [])
        if isinstance(order_history, str):
            import json
            order_history = json.loads(order_history)
        order_history.append({"status": "AWAITING_SHIPMENT", "at": ts})

        conn.execute(
            "UPDATE orders SET status = 'AWAITING_SHIPMENT', status_history = ?, updated_at = ? WHERE order_id = ?",
            (json_dumps(order_history), ts, order_id),
        )

    log_event("escrow", escrow["escrow_id"], "EscrowFunded", "buyer", buyer_id,
              old_state={"status": "PENDING_FUNDING"},
              new_state={"status": "FUNDED", "funding_method": funding_method,
                         "amount_cents": escrow["total_cents"]},
              service="escrow-service")

    log_event("order", order_id, "OrderPaymentReceived", "system", "system",
              old_state={"status": "AWAITING_PAYMENT"},
              new_state={"status": "AWAITING_SHIPMENT"},
              service="order-service")

    return get_escrow(escrow["escrow_id"])


def void_escrow(escrow_id: str, reason: str = "MANUAL") -> dict:
    """Void an unfunded escrow (deadline expired or order cancelled)."""
    escrow = get_escrow(escrow_id)
    if not escrow or escrow["status"] != "PENDING_FUNDING":
        return {"error": "CANNOT_VOID"}

    ts = now_iso()
    history = escrow.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "VOIDED", "at": ts, "reason": reason})

    with get_db() as conn:
        conn.execute(
            "UPDATE escrow_transactions SET status = 'VOIDED', status_history = ?, updated_at = ? WHERE escrow_id = ?",
            (json_dumps(history), ts, escrow_id),
        )

        # Cancel the order
        conn.execute(
            "UPDATE orders SET status = 'CANCELLED', updated_at = ? WHERE order_id = ?",
            (ts, escrow["order_id"]),
        )

        # Re-activate the lot
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (escrow["order_id"],)).fetchone()
        if order_row:
            conn.execute(
                "UPDATE lots SET status = 'ACTIVE', updated_at = ? WHERE lot_id = ?",
                (ts, order_row["lot_id"]),
            )

    log_event("escrow", escrow_id, "EscrowVoided", "system", "system",
              old_state={"status": "PENDING_FUNDING"},
              new_state={"status": "VOIDED", "reason": reason},
              service="escrow-service")

    return get_escrow(escrow_id)


def hold_escrow(escrow_id: str, reason: str, amount_cents: int = None) -> dict:
    """Place a hold on funded escrow (e.g., dispute filed)."""
    escrow = get_escrow(escrow_id)
    if not escrow or escrow["status"] != "FUNDED":
        return {"error": "ESCROW_NOT_FUNDED"}

    ts = now_iso()
    hold_amount = amount_cents or escrow["total_cents"]
    holds = escrow.get("holds", [])
    if isinstance(holds, str):
        import json
        holds = json.loads(holds)
    holds.append({"reason": reason, "amount_cents": hold_amount, "at": ts})

    history = escrow.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "HELD", "at": ts, "reason": reason})

    with get_db() as conn:
        conn.execute(
            "UPDATE escrow_transactions SET status = 'HELD', holds = ?, status_history = ?, updated_at = ? WHERE escrow_id = ?",
            (json_dumps(holds), json_dumps(history), ts, escrow_id),
        )

    log_event("escrow", escrow_id, "EscrowHeld", "system", "system",
              new_state={"status": "HELD", "reason": reason, "hold_amount_cents": hold_amount},
              service="escrow-service")

    return get_escrow(escrow_id)


def release_escrow(escrow_id: str, reason: str = "INSPECTION_ACCEPTED") -> dict:
    """Release escrow funds to seller (after successful inspection)."""
    escrow = get_escrow(escrow_id)
    if not escrow or escrow["status"] not in ("FUNDED", "HELD"):
        return {"error": "ESCROW_NOT_RELEASABLE"}

    ts = now_iso()
    releases = escrow.get("releases", [])
    if isinstance(releases, str):
        import json
        releases = json.loads(releases)
    releases.append({"reason": reason, "amount_cents": escrow["total_cents"], "at": ts})

    history = escrow.get("status_history", [])
    if isinstance(history, str):
        import json
        history = json.loads(history)
    history.append({"status": "RELEASED", "at": ts, "reason": reason})

    with get_db() as conn:
        conn.execute(
            "UPDATE escrow_transactions SET status = 'RELEASED', releases = ?, status_history = ?, updated_at = ? WHERE escrow_id = ?",
            (json_dumps(releases), json_dumps(history), ts, escrow_id),
        )

    log_event("escrow", escrow_id, "EscrowReleased", "system", "system",
              new_state={"status": "RELEASED", "reason": reason,
                         "released_amount_cents": escrow["total_cents"]},
              service="escrow-service")

    return get_escrow(escrow_id)


def check_expired_escrows() -> list:
    """Find and void all escrows past their funding deadline. Call periodically."""
    ts = now_iso()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT escrow_id FROM escrow_transactions WHERE status = 'PENDING_FUNDING' AND funding_deadline < ?",
            (ts,),
        ).fetchall()

    voided = []
    for row in rows:
        result = void_escrow(row["escrow_id"], "FUNDING_DEADLINE_EXPIRED")
        if result and "error" not in result:
            voided.append(row["escrow_id"])
    return voided
