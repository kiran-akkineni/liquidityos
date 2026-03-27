"""
Freight service — carrier quotes, shipment booking, tracking events, delivery detection.
Mock carrier data for V1; structured for ShipEngine integration later.
"""

from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services.audit import log_event
from datetime import datetime, timezone, timedelta
import random

# Mock carrier data
MOCK_CARRIERS = [
    {"name": "FastFreight LTL", "scac": "FFLT", "service": "Standard LTL"},
    {"name": "XPO Logistics", "scac": "XPOL", "service": "LTL Priority"},
    {"name": "Estes Express", "scac": "EXLA", "service": "LTL Economy"},
]

# Rate per pallet by zone (cents)
RATE_PER_PALLET = {
    "same_state": 9500,    # $95
    "adjacent": 12500,     # $125
    "cross_country": 17500, # $175
}


def get_freight_quote(lot_id: str, destination_zip: str, requested_by: str = None) -> dict:
    """Generate mock carrier quotes for a lot. Returns 2-3 options."""
    from app.services.lots import get_lot
    lot = get_lot(lot_id)
    if not lot:
        return {"error": "LOT_NOT_FOUND"}

    origin_zip = lot.get("ship_from_zip", "00000")
    pallet_count = lot.get("pallet_count") or 1
    weight_lb = lot.get("total_weight_lb") or (pallet_count * 800)

    zone = _get_zone(origin_zip, destination_zip, lot.get("ship_from_state"))
    base_rate = RATE_PER_PALLET[zone]

    # Generate 2-3 carrier options with slight price variation
    options = []
    carriers = random.sample(MOCK_CARRIERS, min(len(MOCK_CARRIERS), 3))
    for i, carrier in enumerate(carriers):
        rate_mult = [1.0, 1.15, 0.92][i]
        transit_days = [3, 2, 5][i]
        cost = int(base_rate * pallet_count * rate_mult)

        pickup_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        delivery_date = (datetime.now(timezone.utc) + timedelta(days=1 + transit_days)).strftime("%Y-%m-%d")

        options.append({
            "carrier_name": carrier["name"],
            "carrier_scac": carrier["scac"],
            "service": carrier["service"],
            "cost_cents": cost,
            "transit_days": transit_days,
            "pickup_date": pickup_date,
            "estimated_delivery_date": delivery_date,
            "insurance_available": True,
            "insurance_cents": int(cost * 0.08),
        })

    # Sort by cost
    options.sort(key=lambda o: o["cost_cents"])

    quote_id = make_id("frt_")
    ts = now_iso()

    shipment_specs = {
        "mode": "LTL",
        "weight_lb": weight_lb,
        "pallet_count": pallet_count,
        "cube_cuft": lot.get("total_cube_cuft", 0),
        "freight_class": 125,
    }

    with get_db() as conn:
        conn.execute(
            """INSERT INTO carrier_quotes
               (quote_id, lot_id, requested_by, origin_zip, destination_zip,
                shipment_specs, options, quote_provider, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'mock_v1', ?)""",
            (quote_id, lot_id, requested_by, origin_zip, destination_zip,
             json_dumps(shipment_specs), json_dumps(options), ts),
        )

    log_event("freight", quote_id, "FreightQuoteGenerated", "system", requested_by or "system",
              new_state={"lot_id": lot_id, "options_count": len(options),
                         "cheapest_cents": options[0]["cost_cents"]},
              service="freight-service")

    return get_quote(quote_id)


def get_quote(quote_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM carrier_quotes WHERE quote_id = ?", (quote_id,)).fetchone()
    return dict_from_row(row) if row else None


def book_shipment(order_id: str, quote_id: str, selected_option_index: int = 0) -> dict:
    """Book a shipment from a carrier quote. Called after escrow is funded."""
    quote = get_quote(quote_id)
    if not quote:
        return {"error": "QUOTE_NOT_FOUND"}

    options = quote.get("options", [])
    if selected_option_index >= len(options):
        return {"error": "INVALID_OPTION_INDEX"}

    selected = options[selected_option_index]

    # Get order for origin/dest details
    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not order_row:
        return {"error": "ORDER_NOT_FOUND"}
    order = dict_from_row(order_row)

    # Get lot for origin details
    from app.services.lots import get_lot
    lot = get_lot(order["lot_id"])

    shipment_id = make_id("shp_")
    ts = now_iso()
    tracking_number = f"LQD{random.randint(1000000000, 9999999999)}"
    pro_number = f"PRO{random.randint(100000, 999999)}"

    with get_db() as conn:
        conn.execute(
            """INSERT INTO shipments
               (shipment_id, order_id, quote_id,
                origin_zip, origin_city, origin_state,
                destination_zip, destination_city, destination_state,
                freight_details, carrier_name, carrier_scac, carrier_service,
                cost_cents, insurance_cents, tracking_number, pro_number,
                pickup_scheduled_date, delivery_estimated_date,
                status, status_history, booked_via, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BOOKED', ?, 'platform', ?, ?)""",
            (
                shipment_id, order_id, quote_id,
                lot.get("ship_from_zip"), lot.get("ship_from_city"), lot.get("ship_from_state"),
                quote["destination_zip"], None, None,
                json_dumps(quote.get("shipment_specs", {})),
                selected["carrier_name"], selected["carrier_scac"], selected["service"],
                selected["cost_cents"], selected.get("insurance_cents", 0),
                tracking_number, pro_number,
                selected["pickup_date"], selected["estimated_delivery_date"],
                json_dumps([{"status": "BOOKED", "at": ts}]),
                ts, ts,
            ),
        )

        # Mark selected option on quote
        conn.execute(
            "UPDATE carrier_quotes SET selected_option_index = ? WHERE quote_id = ?",
            (selected_option_index, quote_id),
        )

        # Link shipment to order
        conn.execute(
            "UPDATE orders SET shipment_id = ?, updated_at = ? WHERE order_id = ?",
            (shipment_id, ts, order_id),
        )

    log_event("shipment", shipment_id, "ShipmentBooked", "system", "system",
              new_state={"order_id": order_id, "carrier": selected["carrier_name"],
                         "tracking_number": tracking_number, "cost_cents": selected["cost_cents"]},
              service="freight-service")

    return get_shipment(shipment_id)


def get_shipment(shipment_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM shipments WHERE shipment_id = ?", (shipment_id,)).fetchone()
    return dict_from_row(row) if row else None


def get_shipment_by_order(order_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchone()
    return dict_from_row(row) if row else None


def add_tracking_event(shipment_id: str, status: str, description: str,
                       location_city: str = None, location_state: str = None,
                       location_zip: str = None) -> dict:
    """Add a tracking event and update shipment status."""
    shipment = get_shipment(shipment_id)
    if not shipment:
        return {"error": "SHIPMENT_NOT_FOUND"}

    event_id = make_id("trk_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO tracking_events
               (event_id, shipment_id, timestamp, status, location_city, location_state,
                location_zip, description, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'carrier_api', ?)""",
            (event_id, shipment_id, ts, status, location_city, location_state,
             location_zip, description, ts),
        )

        # Update shipment status
        history = shipment.get("status_history", [])
        if isinstance(history, str):
            import json
            history = json.loads(history)
        history.append({"status": status, "at": ts})

        update_fields = {"status": status, "status_history": json_dumps(history), "updated_at": ts}

        if status == "PICKED_UP":
            update_fields["pickup_confirmed_at"] = ts
        elif status == "DELIVERED":
            update_fields["delivery_actual_date"] = ts.split("T")[0]
            update_fields["delivery_delivered_at"] = ts

        set_clause = ", ".join(f"{k} = ?" for k in update_fields)
        conn.execute(
            f"UPDATE shipments SET {set_clause} WHERE shipment_id = ?",
            (*update_fields.values(), shipment_id),
        )

    # If delivered, update order status and open inspection window
    if status == "DELIVERED":
        _on_delivery(shipment)

    return {"event_id": event_id, "shipment": get_shipment(shipment_id)}


def update_order_shipped(order_id: str) -> dict:
    """Transition order to SHIPPED status when shipment is picked up."""
    ts = now_iso()
    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if not order_row:
            return {"error": "ORDER_NOT_FOUND"}
        order = dict_from_row(order_row)

        if order["status"] != "AWAITING_SHIPMENT":
            return {"error": "ORDER_NOT_AWAITING_SHIPMENT"}

        history = order.get("status_history", [])
        if isinstance(history, str):
            import json
            history = json.loads(history)
        history.append({"status": "SHIPPED", "at": ts})

        conn.execute(
            "UPDATE orders SET status = 'SHIPPED', status_history = ?, updated_at = ? WHERE order_id = ?",
            (json_dumps(history), ts, order_id),
        )

    log_event("order", order_id, "OrderShipped", "system", "system",
              old_state={"status": "AWAITING_SHIPMENT"},
              new_state={"status": "SHIPPED"},
              service="order-service")

    return {"status": "SHIPPED"}


def _on_delivery(shipment: dict):
    """Handle delivery: transition order to DELIVERED, then INSPECTION with 48h window."""
    order_id = shipment["order_id"]
    ts = now_iso()
    inspection_opens = ts
    inspection_closes = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        order = dict_from_row(order_row)

        history = order.get("status_history", [])
        if isinstance(history, str):
            import json
            history = json.loads(history)
        history.append({"status": "DELIVERED", "at": ts})
        history.append({"status": "INSPECTION", "at": ts})

        conn.execute(
            """UPDATE orders
               SET status = 'INSPECTION', status_history = ?,
                   inspection_window_opens_at = ?, inspection_window_closes_at = ?,
                   updated_at = ?
               WHERE order_id = ?""",
            (json_dumps(history), inspection_opens, inspection_closes, ts, order_id),
        )

    log_event("order", order_id, "OrderDelivered", "system", "system",
              new_state={"status": "INSPECTION",
                         "inspection_window_closes_at": inspection_closes},
              service="order-service")


def get_tracking_events(shipment_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY timestamp",
            (shipment_id,),
        ).fetchall()
    return rows_to_dicts(rows)


def _get_zone(origin_zip: str, destination_zip: str, origin_state: str = None) -> str:
    """Simple zone classification based on zip prefix."""
    o_prefix = origin_zip[:3] if origin_zip else "000"
    d_prefix = destination_zip[:3] if destination_zip else "999"

    if o_prefix == d_prefix:
        return "same_state"
    # Rough adjacency: same first digit
    if o_prefix[0] == d_prefix[0]:
        return "adjacent"
    return "cross_country"
