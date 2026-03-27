"""
Lot service — creation from ingestion jobs, activation, search, management.
"""

from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import make_id, now_iso, json_dumps, CONDITION_ORDER
from app.services.audit import log_event


def create_lot(seller_id: str, data: dict) -> dict:
    """Create a lot (DRAFT status) from ingestion job or manual input."""
    lot_id = make_id("lot_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO lots
               (lot_id, seller_id, job_id, status, title, description,
                total_units, total_skus, total_weight_lb, total_cube_cuft,
                pallet_count, packing_type, estimated_retail_value_cents, total_cost_cents,
                condition_distribution, condition_primary, category_primary, categories,
                top_brands, ship_from_zip, ship_from_state, ship_from_city,
                ship_from_location_id, media, created_at, updated_at)
               VALUES (?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                lot_id, seller_id,
                data.get("job_id"),
                data.get("title", "Untitled Lot"),
                data.get("description"),
                data.get("total_units", 0),
                data.get("total_skus", 0),
                data.get("total_weight_lb", 0),
                data.get("total_cube_cuft", 0),
                data.get("pallet_count", 0),
                data.get("packing_type", "pallet"),
                data.get("estimated_retail_value_cents", 0),
                data.get("total_cost_cents", 0),
                json_dumps(data.get("condition_distribution", {})),
                data.get("condition_primary", "GOOD"),
                data.get("category_primary"),
                json_dumps(data.get("categories", {})),
                json_dumps(data.get("top_brands", [])),
                data.get("ship_from_zip"),
                data.get("ship_from_state"),
                data.get("ship_from_city"),
                data.get("ship_from_location_id"),
                json_dumps(data.get("media", {})),
                ts, ts,
            ),
        )

    log_event("lot", lot_id, "LotDraftCreated", "seller", seller_id,
              new_state={"status": "DRAFT"}, service="lot-service")

    return get_lot(lot_id)


def get_lot(lot_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lots WHERE lot_id = ? AND deleted_at IS NULL", (lot_id,)).fetchone()
    return dict_from_row(row) if row else None


def activate_lot(lot_id: str, seller_id: str, pricing: dict) -> dict:
    """Activate a lot: set pricing and enter matching pool."""
    ts = now_iso()
    lot = get_lot(lot_id)
    if not lot or lot["seller_id"] != seller_id:
        return None
    if lot["status"] != "DRAFT":
        return None

    # Default expiry: 14 days from activation
    from datetime import datetime, timezone, timedelta
    expires = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_db() as conn:
        conn.execute(
            """UPDATE lots SET
               status = 'ACTIVE',
               pricing_mode = ?,
               ask_price_cents = ?,
               floor_price_cents = ?,
               time_decay_schedule = ?,
               expires_at = ?,
               activated_at = ?,
               updated_at = ?
               WHERE lot_id = ? AND seller_id = ?""",
            (
                pricing.get("mode", "MAKE_OFFER"),
                pricing["ask_price_cents"],
                pricing.get("floor_price_cents", int(pricing["ask_price_cents"] * 0.75)),
                json_dumps(pricing.get("time_decay_schedule", {})),
                expires,
                ts, ts,
                lot_id, seller_id,
            ),
        )

    log_event("lot", lot_id, "LotActivated", "seller", seller_id,
              old_state={"status": "DRAFT"},
              new_state={"status": "ACTIVE", "ask_price_cents": pricing["ask_price_cents"]},
              service="lot-service")

    return get_lot(lot_id)


def search_lots(filters: dict) -> list:
    """Search active lots with buyer-facing filters."""
    conditions = ["status = 'ACTIVE'", "deleted_at IS NULL"]
    params = []

    if filters.get("categories"):
        placeholders = ",".join("?" for _ in filters["categories"])
        conditions.append(f"category_primary IN ({placeholders})")
        params.extend(filters["categories"])

    if filters.get("condition_min"):
        min_order = CONDITION_ORDER.get(filters["condition_min"], 0)
        valid_conditions = [k for k, v in CONDITION_ORDER.items() if v >= min_order]
        placeholders = ",".join("?" for _ in valid_conditions)
        conditions.append(f"condition_primary IN ({placeholders})")
        params.extend(valid_conditions)

    if filters.get("max_lot_cost_cents"):
        conditions.append("ask_price_cents <= ?")
        params.append(filters["max_lot_cost_cents"])

    limit = min(filters.get("limit", 20), 50)
    offset = filters.get("offset", 0)

    sort_map = {
        "price_asc": "ask_price_cents ASC",
        "price_desc": "ask_price_cents DESC",
        "newest": "activated_at DESC",
        "match_score_desc": "activated_at DESC",  # placeholder; real matching uses a scoring service
    }
    sort = sort_map.get(filters.get("sort_by"), "activated_at DESC")

    sql = f"SELECT * FROM lots WHERE {' AND '.join(conditions)} ORDER BY {sort} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM lots WHERE {' AND '.join(conditions[:-0] if not conditions else conditions)}",
            params[:-2]  # exclude limit/offset
        ).fetchone()

    return {
        "lots": rows_to_dicts(rows),
        "pagination": {
            "total": total["cnt"] if total else 0,
            "returned": len(rows),
            "limit": limit,
            "offset": offset,
        },
    }


def update_lot_status(lot_id: str, new_status: str, actor_id: str, actor_type: str = "system") -> dict:
    """Update lot status with audit logging."""
    lot = get_lot(lot_id)
    if not lot:
        return None
    old_status = lot["status"]
    ts = now_iso()

    with get_db() as conn:
        updates = {"status": new_status, "updated_at": ts}
        if new_status == "SOLD":
            updates["sold_at"] = ts
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE lots SET {set_clause} WHERE lot_id = ?",
            list(updates.values()) + [lot_id],
        )

    log_event("lot", lot_id, f"Lot{new_status.title().replace('_', '')}",
              actor_type, actor_id,
              old_state={"status": old_status}, new_state={"status": new_status},
              service="lot-service")

    return get_lot(lot_id)
