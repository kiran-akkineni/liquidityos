"""
Buyer service — account management, verification, intent profiles.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event


def register_buyer(data: dict) -> dict:
    """Register a new buyer."""
    buyer_id = make_id("buy_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO buyers
               (buyer_id, status, buyer_type, business_name, ein_tin,
                resale_certificate, primary_contact_name, primary_contact_email,
                primary_contact_phone, sales_channels, primary_channel,
                warehouses, estimated_monthly_volume_cents, created_at, updated_at)
               VALUES (?, 'PENDING_VERIFICATION', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                buyer_id,
                data.get("buyer_type", "ecom_reseller"),
                data["business_name"],
                data.get("ein_tin"),
                json_dumps(data.get("resale_certificate", {})),
                data["primary_contact_name"],
                data["primary_contact_email"],
                data.get("primary_contact_phone"),
                json_dumps(data.get("sales_channels", [])),
                data.get("primary_channel"),
                json_dumps(data.get("warehouses", [])),
                data.get("estimated_monthly_volume_cents", 0),
                ts, ts,
            ),
        )

    log_event("buyer", buyer_id, "BuyerRegistered", "buyer", buyer_id,
              new_state={"status": "PENDING_VERIFICATION", "buyer_type": data.get("buyer_type")},
              service="account-service")

    return get_buyer(buyer_id)


def get_buyer(buyer_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM buyers WHERE buyer_id = ? AND deleted_at IS NULL", (buyer_id,)).fetchone()
    return dict_from_row(row) if row else None


def verify_buyer(buyer_id: str, decision: str, actor_id: str) -> dict:
    ts = now_iso()
    old = get_buyer(buyer_id)
    if not old:
        return None

    new_status = "ACTIVE" if decision == "APPROVED" else "DEACTIVATED"
    event = "BuyerVerified" if decision == "APPROVED" else "BuyerRejected"

    with get_db() as conn:
        conn.execute(
            "UPDATE buyers SET status = ?, verified_at = ?, updated_at = ? WHERE buyer_id = ?",
            (new_status, ts if decision == "APPROVED" else None, ts, buyer_id),
        )

    log_event("buyer", buyer_id, event, "ops", actor_id,
              old_state={"status": old["status"]}, new_state={"status": new_status},
              service="account-service")

    return get_buyer(buyer_id)


# ── Intent Profiles ──

def create_intent_profile(buyer_id: str, data: dict) -> dict:
    """Create a buyer intent profile."""
    profile_id = make_id("bip_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO buyer_intent_profiles
               (profile_id, buyer_id, profile_name, is_active,
                category_filters, brand_filters, condition_min,
                channel_config, economics, logistics, trust_filters,
                automation, notifications, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile_id, buyer_id,
                data.get("profile_name", "Default"),
                json_dumps(data.get("category_filters", {})),
                json_dumps(data.get("brand_filters", {})),
                data.get("condition_min", "GOOD"),
                json_dumps(data.get("channel_config", {})),
                json_dumps(data.get("economics", {})),
                json_dumps(data.get("logistics", {})),
                json_dumps(data.get("trust_filters", {})),
                json_dumps(data.get("automation", {})),
                json_dumps(data.get("notifications", {})),
                ts, ts,
            ),
        )

    log_event("buyer_intent_profile", profile_id, "BuyerIntentProfileCreated",
              "buyer", buyer_id, new_state={"profile_name": data.get("profile_name")},
              service="account-service")

    return get_intent_profile(profile_id)


def get_intent_profile(profile_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM buyer_intent_profiles WHERE profile_id = ?", (profile_id,)).fetchone()
    return dict_from_row(row) if row else None


def list_intent_profiles(buyer_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM buyer_intent_profiles WHERE buyer_id = ? ORDER BY created_at DESC",
            (buyer_id,)
        ).fetchall()
    return [dict_from_row(r) for r in rows]


def update_intent_profile(profile_id: str, buyer_id: str, data: dict) -> dict:
    ts = now_iso()
    allowed = ["profile_name", "is_active", "category_filters", "brand_filters",
               "condition_min", "channel_config", "economics", "logistics",
               "trust_filters", "automation", "notifications"]
    updates, values = [], []
    for field in allowed:
        if field in data:
            val = data[field]
            if isinstance(val, (dict, list)):
                val = json_dumps(val)
            updates.append(f"{field} = ?")
            values.append(val)

    if not updates:
        return get_intent_profile(profile_id)

    updates.append("updated_at = ?")
    values.extend([ts, profile_id, buyer_id])

    with get_db() as conn:
        conn.execute(
            f"UPDATE buyer_intent_profiles SET {', '.join(updates)} WHERE profile_id = ? AND buyer_id = ?",
            values,
        )
    return get_intent_profile(profile_id)
