"""
Offer service — create, accept, counter, decline offers. Order creation on acceptance.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import make_id, now_iso, json_dumps, PLATFORM_FEE_PCT
from app.services.audit import log_event
from datetime import datetime, timezone, timedelta


def create_offer(buyer_id: str, data: dict) -> dict:
    """Create a new offer on a lot."""
    from app.services.lots import get_lot
    from app.services.buyers import get_buyer

    lot = get_lot(data["lot_id"])
    if not lot or lot["status"] != "ACTIVE":
        return {"error": "LOT_NOT_AVAILABLE"}

    buyer = get_buyer(buyer_id)
    if not buyer or buyer["status"] != "ACTIVE":
        return {"error": "BUYER_NOT_ACTIVE"}

    # Check purchase limit
    if data["offered_price_cents"] > buyer.get("purchase_limit_remaining_cents", 0):
        return {"error": "EXCEEDS_PURCHASE_LIMIT"}

    # Check floor price (don't reveal floor)
    floor = lot.get("floor_price_cents", 0)
    if floor and data["offered_price_cents"] < floor:
        return {"error": "OFFER_BELOW_MINIMUM",
                "message": "Your offer is below the acceptable range for this lot."}

    offer_id = make_id("off_")
    ts = now_iso()
    valid_until = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    offer_type = data.get("offer_type", "MAKE_OFFER")

    # If ACCEPT_ASK, set price to ask price
    price = lot["ask_price_cents"] if offer_type == "ACCEPT_ASK" else data["offered_price_cents"]

    with get_db() as conn:
        conn.execute(
            """INSERT INTO offers
               (offer_id, lot_id, buyer_id, offer_type, offered_price_cents,
                conditions, buyer_message, simulation_id, status, status_history,
                valid_until, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)""",
            (
                offer_id, data["lot_id"], buyer_id, offer_type, price,
                json_dumps(data.get("conditions", [])),
                data.get("message"),
                data.get("simulation_id"),
                json_dumps([{"status": "PENDING", "at": ts, "actor": buyer_id}]),
                valid_until, ts, ts,
            ),
        )

        # Increment lot offer count
        conn.execute("UPDATE lots SET offers_received = offers_received + 1 WHERE lot_id = ?",
                      (data["lot_id"],))

    log_event("offer", offer_id, "OfferPlaced", "buyer", buyer_id,
              new_state={"lot_id": data["lot_id"], "offered_price_cents": price, "offer_type": offer_type},
              service="offer-service")

    # If ACCEPT_ASK or seller has auto-accept rule matching, auto-accept
    if offer_type == "ACCEPT_ASK":
        return accept_offer(offer_id, lot["seller_id"])

    # Check seller auto-accept rules
    seller_rules = lot.get("auto_accept_rules") or []
    # Simple check: not implemented in detail for V1 — manual acceptance
    # TODO: evaluate auto_accept_rules

    return get_offer(offer_id)


def get_offer(offer_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()
    return dict_from_row(row) if row else None


def accept_offer(offer_id: str, seller_id: str) -> dict:
    """Seller accepts an offer → create order."""
    offer = get_offer(offer_id)
    if not offer or offer["status"] != "PENDING":
        return {"error": "OFFER_NOT_PENDING"}

    ts = now_iso()

    with get_db() as conn:
        # Update offer
        conn.execute(
            "UPDATE offers SET status = 'ACCEPTED', updated_at = ? WHERE offer_id = ?",
            (ts, offer_id)
        )

        # Decline other pending offers on this lot
        conn.execute(
            "UPDATE offers SET status = 'VOIDED', updated_at = ? WHERE lot_id = ? AND offer_id != ? AND status = 'PENDING'",
            (ts, offer["lot_id"], offer_id)
        )

        # Update lot status
        conn.execute(
            "UPDATE lots SET status = 'UNDER_CONTRACT', updated_at = ? WHERE lot_id = ?",
            (ts, offer["lot_id"])
        )

    log_event("offer", offer_id, "OfferAccepted", "seller", seller_id,
              new_state={"accepted_price": offer["offered_price_cents"]},
              service="offer-service")

    # Create order
    order = _create_order(offer, seller_id)
    return {"offer": get_offer(offer_id), "order": order}


def counter_offer(offer_id: str, seller_id: str, counter_price_cents: int, message: str = None) -> dict:
    """Seller counters an offer."""
    offer = get_offer(offer_id)
    if not offer or offer["status"] != "PENDING":
        return {"error": "OFFER_NOT_PENDING"}

    # Check round count (max 3)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) as cnt FROM counter_offers WHERE offer_id = ?",
            (offer_id,)
        ).fetchone()
    if existing["cnt"] >= 3:
        return {"error": "MAX_COUNTER_ROUNDS_REACHED"}

    counter_id = make_id("ctr_")
    ts = now_iso()
    valid_until = (datetime.now(timezone.utc) + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO counter_offers
               (counter_id, offer_id, lot_id, seller_id, counter_price_cents,
                counter_message, round_number, status, status_history,
                valid_until, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_BUYER', ?, ?, ?, ?)""",
            (
                counter_id, offer_id, offer["lot_id"], seller_id,
                counter_price_cents, message,
                (existing["cnt"] or 0) + 1,
                json_dumps([{"status": "PENDING_BUYER", "at": ts}]),
                valid_until, ts, ts,
            ),
        )

        conn.execute(
            "UPDATE offers SET status = 'COUNTERED', counter_offer_id = ?, updated_at = ? WHERE offer_id = ?",
            (counter_id, ts, offer_id)
        )

    log_event("offer", offer_id, "CounterOfferSent", "seller", seller_id,
              new_state={"counter_id": counter_id, "counter_price_cents": counter_price_cents},
              service="offer-service")

    return {"offer": get_offer(offer_id), "counter": get_counter(counter_id)}


def accept_counter(counter_id: str, buyer_id: str) -> dict:
    """Buyer accepts a counter-offer."""
    counter = get_counter(counter_id)
    if not counter or counter["status"] != "PENDING_BUYER":
        return {"error": "COUNTER_NOT_PENDING"}

    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            "UPDATE counter_offers SET status = 'ACCEPTED', updated_at = ? WHERE counter_id = ?",
            (ts, counter_id)
        )
        # Update the original offer's price to counter price and accept
        conn.execute(
            "UPDATE offers SET status = 'ACCEPTED', offered_price_cents = ?, updated_at = ? WHERE offer_id = ?",
            (counter["counter_price_cents"], ts, counter["offer_id"])
        )
        # Void other offers
        offer = get_offer(counter["offer_id"])
        conn.execute(
            "UPDATE offers SET status = 'VOIDED', updated_at = ? WHERE lot_id = ? AND offer_id != ? AND status IN ('PENDING','COUNTERED')",
            (ts, counter["lot_id"], counter["offer_id"])
        )
        conn.execute(
            "UPDATE lots SET status = 'UNDER_CONTRACT', updated_at = ? WHERE lot_id = ?",
            (ts, counter["lot_id"])
        )

    log_event("offer", counter["offer_id"], "CounterOfferAccepted", "buyer", buyer_id,
              new_state={"accepted_price": counter["counter_price_cents"]},
              service="offer-service")

    updated_offer = get_offer(counter["offer_id"])
    order = _create_order(updated_offer, counter["seller_id"])
    return {"offer": updated_offer, "counter": get_counter(counter_id), "order": order}


def decline_offer(offer_id: str, seller_id: str) -> dict:
    ts = now_iso()
    with get_db() as conn:
        conn.execute("UPDATE offers SET status = 'DECLINED', updated_at = ? WHERE offer_id = ?", (ts, offer_id))
    log_event("offer", offer_id, "OfferDeclined", "seller", seller_id, service="offer-service")
    return get_offer(offer_id)


def get_counter(counter_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM counter_offers WHERE counter_id = ?", (counter_id,)).fetchone()
    return dict_from_row(row) if row else None


def _create_order(offer: dict, seller_id: str) -> dict:
    """Create an order from an accepted offer."""
    from app.services.lots import get_lot

    lot = get_lot(offer["lot_id"])
    price = offer["offered_price_cents"]
    platform_fee = int(price * PLATFORM_FEE_PCT)
    freight = 19000  # V1 placeholder; real freight quote in production
    insurance = int(price * 0.01)
    total = price + platform_fee + freight + insurance
    payout = price - platform_fee

    order_id = make_id("ord_")
    ts = now_iso()

    with get_db() as conn:
        conn.execute(
            """INSERT INTO orders
               (order_id, lot_id, offer_id, counter_id, buyer_id, seller_id,
                status, status_history,
                lot_price_cents, platform_fee_cents, platform_fee_rate_pct,
                freight_cost_cents, insurance_cents, total_buyer_cost_cents,
                seller_payout_cents, platform_revenue_cents,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'AWAITING_PAYMENT', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order_id, offer["lot_id"], offer["offer_id"],
                offer.get("counter_offer_id"),
                offer["buyer_id"], seller_id,
                json_dumps([{"status": "CREATED", "at": ts}, {"status": "AWAITING_PAYMENT", "at": ts}]),
                price, platform_fee, PLATFORM_FEE_PCT * 100,
                freight, insurance, total, payout, platform_fee,
                ts, ts,
            ),
        )

    log_event("order", order_id, "OrderCreated", "system", "system",
              new_state={"status": "AWAITING_PAYMENT", "total": total},
              service="order-service")

    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    return dict_from_row(row)
