"""
Seller service — account management, verification, profile.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event


def register_seller(data: dict) -> dict:
    """Register a new seller."""
    seller_id = make_id("sel_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO sellers
               (seller_id, status, seller_type, business_name, dba_name, ein_tin,
                state_of_incorporation, primary_contact_name, primary_contact_email,
                primary_contact_phone, warehouse_locations, estimated_monthly_volume_cents,
                estimated_monthly_pallets, created_at, updated_at)
               VALUES (?, 'PENDING_VERIFICATION', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                seller_id,
                data.get("seller_type", "other"),
                data["business_name"],
                data.get("dba_name"),
                data.get("ein_tin"),
                data.get("state_of_incorporation"),
                data["primary_contact_name"],
                data["primary_contact_email"],
                data.get("primary_contact_phone"),
                json_dumps(data.get("warehouse_locations", [])),
                data.get("estimated_monthly_volume_cents", 0),
                data.get("estimated_monthly_pallets", 0),
                ts, ts,
            ),
        )

    log_event("seller", seller_id, "SellerRegistered", "seller", seller_id,
              new_state={"status": "PENDING_VERIFICATION", "seller_type": data.get("seller_type")},
              service="account-service")

    return get_seller(seller_id)


def get_seller(seller_id: str) -> dict:
    """Get seller by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sellers WHERE seller_id = ? AND deleted_at IS NULL", (seller_id,)).fetchone()
    return dict_from_row(row) if row else None


def verify_seller(seller_id: str, decision: str, actor_id: str) -> dict:
    """Approve or reject a seller. Decision: APPROVED | REJECTED."""
    ts = now_iso()
    old = get_seller(seller_id)
    if not old:
        return None

    if decision == "APPROVED":
        new_status = "ACTIVE"
        event = "SellerVerified"
    else:
        new_status = "DEACTIVATED"
        event = "SellerRejected"

    with get_db() as conn:
        conn.execute(
            "UPDATE sellers SET status = ?, verified_at = ?, updated_at = ? WHERE seller_id = ?",
            (new_status, ts if decision == "APPROVED" else None, ts, seller_id),
        )

    log_event("seller", seller_id, event, "ops", actor_id,
              old_state={"status": old["status"]},
              new_state={"status": new_status},
              service="account-service")

    return get_seller(seller_id)


def update_seller(seller_id: str, data: dict) -> dict:
    """Update seller profile fields."""
    ts = now_iso()
    allowed_fields = ["business_name", "dba_name", "primary_contact_name",
                      "primary_contact_email", "primary_contact_phone",
                      "warehouse_locations", "payment_info", "auto_accept_rules"]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            val = data[field]
            if isinstance(val, (dict, list)):
                val = json_dumps(val)
            updates.append(f"{field} = ?")
            values.append(val)

    if not updates:
        return get_seller(seller_id)

    updates.append("updated_at = ?")
    values.append(ts)
    values.append(seller_id)

    with get_db() as conn:
        conn.execute(
            f"UPDATE sellers SET {', '.join(updates)} WHERE seller_id = ?",
            values,
        )
    return get_seller(seller_id)


def list_sellers(status: str = None, limit: int = 20, offset: int = 0) -> list:
    """List sellers with optional status filter."""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM sellers WHERE status = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sellers WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
    return [dict_from_row(r) for r in rows]
