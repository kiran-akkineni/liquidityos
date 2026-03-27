"""
LiquidityOS API Routes — REST endpoints for the commerce backend.
"""

from flask import Blueprint, request, jsonify, g
from app.middleware.auth import require_auth, create_token
from app.services import sellers, buyers, lots, pricing, offers
from app.services import escrow as escrow_svc, invoices as invoice_svc
from app.services import freight as freight_svc, fulfillment as fulfillment_svc
from app.services import disputes as dispute_svc
from app.services.audit import log_event

api = Blueprint("api", __name__, url_prefix="/v1")


# ════════════════════════════════════════
# HEALTH
# ════════════════════════════════════════

@api.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "liquidityos", "version": "0.1.0"})


# ════════════════════════════════════════
# AUTH (simplified for development)
# ════════════════════════════════════════

@api.route("/auth/token", methods=["POST"])
def get_token():
    """Dev-only: issue a token for a user_id + role."""
    data = request.get_json()
    if not data or "user_id" not in data or "role" not in data:
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "user_id and role required"}}), 400
    token = create_token(data["user_id"], data["role"])
    return jsonify({"token": token, "user_id": data["user_id"], "role": data["role"]})


# ════════════════════════════════════════
# SELLERS
# ════════════════════════════════════════

@api.route("/sellers", methods=["POST"])
def register_seller():
    data = request.get_json()
    required = ["business_name", "primary_contact_name", "primary_contact_email"]
    for field in required:
        if field not in data:
            return jsonify({"error": {"code": "MISSING_FIELD", "message": f"{field} is required"}}), 400
    seller = sellers.register_seller(data)
    token = create_token(seller["seller_id"], "seller")
    return jsonify({"seller": seller, "token": token}), 201


@api.route("/sellers/me", methods=["GET"])
@require_auth("seller")
def get_current_seller():
    seller = sellers.get_seller(g.current_user_id)
    if not seller:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(seller)


@api.route("/sellers/me", methods=["PUT"])
@require_auth("seller")
def update_current_seller():
    data = request.get_json()
    seller = sellers.update_seller(g.current_user_id, data)
    return jsonify(seller)


# ════════════════════════════════════════
# BUYERS
# ════════════════════════════════════════

@api.route("/buyers", methods=["POST"])
def register_buyer():
    data = request.get_json()
    required = ["business_name", "primary_contact_name", "primary_contact_email"]
    for field in required:
        if field not in data:
            return jsonify({"error": {"code": "MISSING_FIELD", "message": f"{field} is required"}}), 400
    buyer = buyers.register_buyer(data)
    token = create_token(buyer["buyer_id"], "buyer")
    return jsonify({"buyer": buyer, "token": token}), 201


@api.route("/buyers/me", methods=["GET"])
@require_auth("buyer")
def get_current_buyer():
    buyer = buyers.get_buyer(g.current_user_id)
    if not buyer:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(buyer)


# ── Intent Profiles ──

@api.route("/buyers/me/intent-profiles", methods=["POST"])
@require_auth("buyer")
def create_intent_profile():
    data = request.get_json()
    profile = buyers.create_intent_profile(g.current_user_id, data)
    return jsonify(profile), 201


@api.route("/buyers/me/intent-profiles", methods=["GET"])
@require_auth("buyer")
def list_intent_profiles():
    profiles = buyers.list_intent_profiles(g.current_user_id)
    return jsonify({"profiles": profiles})


@api.route("/buyers/me/intent-profiles/<profile_id>", methods=["PUT"])
@require_auth("buyer")
def update_intent_profile(profile_id):
    data = request.get_json()
    profile = buyers.update_intent_profile(profile_id, g.current_user_id, data)
    if not profile:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(profile)


# ════════════════════════════════════════
# LOTS
# ════════════════════════════════════════

@api.route("/lots", methods=["POST"])
@require_auth("seller")
def create_lot():
    data = request.get_json()
    lot = lots.create_lot(g.current_user_id, data)
    return jsonify(lot), 201


@api.route("/lots/<lot_id>", methods=["GET"])
@require_auth("seller", "buyer", "ops")
def get_lot(lot_id):
    lot = lots.get_lot(lot_id)
    if not lot:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(lot)


@api.route("/lots/<lot_id>/activate", methods=["POST"])
@require_auth("seller")
def activate_lot(lot_id):
    data = request.get_json()
    if "ask_price_cents" not in data:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "ask_price_cents required"}}), 400
    lot = lots.activate_lot(lot_id, g.current_user_id, data)
    if not lot:
        return jsonify({"error": {"code": "ACTIVATION_FAILED", "message": "Lot not found or not in DRAFT status"}}), 400
    return jsonify(lot)


@api.route("/lots", methods=["GET"])
@require_auth("buyer", "ops")
def search_lots():
    filters = {
        "categories": request.args.getlist("categories"),
        "condition_min": request.args.get("condition_min"),
        "max_lot_cost_cents": _int_param("max_lot_cost_cents"),
        "sort_by": request.args.get("sort_by", "newest"),
        "limit": _int_param("limit", 20),
        "offset": _int_param("offset", 0),
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}
    result = lots.search_lots(filters)
    return jsonify(result)


# ════════════════════════════════════════
# PRICING + MARGIN
# ════════════════════════════════════════

@api.route("/lots/<lot_id>/pricing", methods=["GET"])
@require_auth("seller", "ops")
def get_pricing_recommendation(lot_id):
    rec = pricing.generate_pricing_recommendation(lot_id)
    if not rec:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(rec)


@api.route("/lots/<lot_id>/margin-simulation", methods=["POST"])
@require_auth("buyer")
def compute_margin_simulation(lot_id):
    data = request.get_json()
    if "channel" not in data or "destination_zip" not in data:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "channel and destination_zip required"}}), 400
    sim = pricing.compute_margin_simulation(
        lot_id, g.current_user_id,
        data["channel"], data["destination_zip"],
        data.get("purchase_price_cents"),
    )
    if not sim:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(sim)


# ════════════════════════════════════════
# OFFERS + NEGOTIATION
# ════════════════════════════════════════

@api.route("/offers", methods=["POST"])
@require_auth("buyer")
def create_offer():
    data = request.get_json()
    required = ["lot_id", "offered_price_cents"]
    for field in required:
        if field not in data:
            return jsonify({"error": {"code": "MISSING_FIELD", "message": f"{field} required"}}), 400
    result = offers.create_offer(g.current_user_id, data)
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"], "message": result.get("message", "")}}), 400
    return jsonify(result), 201


@api.route("/offers/<offer_id>", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_offer(offer_id):
    offer = offers.get_offer(offer_id)
    if not offer:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(offer)


@api.route("/offers/<offer_id>/accept", methods=["POST"])
@require_auth("seller")
def accept_offer(offer_id):
    result = offers.accept_offer(offer_id, g.current_user_id)
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 400
    return jsonify(result)


@api.route("/offers/<offer_id>/counter", methods=["POST"])
@require_auth("seller")
def counter_offer(offer_id):
    data = request.get_json()
    if "counter_price_cents" not in data:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "counter_price_cents required"}}), 400
    result = offers.counter_offer(offer_id, g.current_user_id,
                                   data["counter_price_cents"], data.get("message"))
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 400
    return jsonify(result)


@api.route("/offers/<offer_id>/decline", methods=["POST"])
@require_auth("seller")
def decline_offer(offer_id):
    result = offers.decline_offer(offer_id, g.current_user_id)
    return jsonify(result)


@api.route("/counters/<counter_id>/accept", methods=["POST"])
@require_auth("buyer")
def accept_counter(counter_id):
    result = offers.accept_counter(counter_id, g.current_user_id)
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 400
    return jsonify(result)


# ════════════════════════════════════════
# ORDERS
# ════════════════════════════════════════

@api.route("/orders/<order_id>", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_order(order_id):
    from app.db import get_db, dict_from_row
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(dict_from_row(row))


@api.route("/orders", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def list_orders():
    from app.db import get_db, rows_to_dicts
    status = request.args.get("status")
    limit = _int_param("limit", 20)

    with get_db() as conn:
        if g.current_role == "buyer":
            if status and status != "ALL":
                rows = conn.execute(
                    "SELECT * FROM orders WHERE buyer_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                    (g.current_user_id, status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE buyer_id = ? ORDER BY created_at DESC LIMIT ?",
                    (g.current_user_id, limit)
                ).fetchall()
        elif g.current_role == "seller":
            if status and status != "ALL":
                rows = conn.execute(
                    "SELECT * FROM orders WHERE seller_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                    (g.current_user_id, status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE seller_id = ? ORDER BY created_at DESC LIMIT ?",
                    (g.current_user_id, limit)
                ).fetchall()
        else:  # ops
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

    return jsonify({"orders": rows_to_dicts(rows)})


# ════════════════════════════════════════
# ESCROW + PAYMENT
# ════════════════════════════════════════

@api.route("/orders/<order_id>/escrow", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_escrow(order_id):
    esc = escrow_svc.get_escrow_by_order(order_id)
    if not esc:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(esc)


@api.route("/orders/<order_id>/escrow/fund", methods=["POST"])
@require_auth("buyer")
def fund_escrow(order_id):
    data = request.get_json() or {}
    result = escrow_svc.fund_escrow(order_id, g.current_user_id, data)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "ESCROW_NOT_FOUND":
            status = 404
        elif code == "NOT_AUTHORIZED":
            status = 403
        elif code == "FUNDING_DEADLINE_EXPIRED":
            status = 410
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status

    # Generate invoices on successful funding
    from app.db import get_db, dict_from_row
    with get_db() as conn:
        order_row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if order_row:
        order = dict_from_row(order_row)
        invoice_svc.generate_invoices(order)

    return jsonify(result)


@api.route("/orders/<order_id>/invoices", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_order_invoices(order_id):
    invs = invoice_svc.get_invoices_by_order(order_id)
    return jsonify({"invoices": invs})


# ════════════════════════════════════════
# FREIGHT + SHIPMENTS
# ════════════════════════════════════════

@api.route("/lots/<lot_id>/freight-quotes", methods=["POST"])
@require_auth("buyer", "seller", "ops")
def get_freight_quote(lot_id):
    data = request.get_json() or {}
    destination_zip = data.get("destination_zip")
    if not destination_zip:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "destination_zip required"}}), 400
    result = freight_svc.get_freight_quote(lot_id, destination_zip, g.current_user_id)
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 404
    return jsonify(result), 201


@api.route("/orders/<order_id>/shipment/book", methods=["POST"])
@require_auth("seller", "ops")
def book_shipment(order_id):
    data = request.get_json() or {}
    quote_id = data.get("quote_id")
    if not quote_id:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "quote_id required"}}), 400
    selected_index = data.get("selected_option_index", 0)
    result = freight_svc.book_shipment(order_id, quote_id, selected_index)
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 400
    return jsonify(result), 201


@api.route("/orders/<order_id>/shipment", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_shipment(order_id):
    shipment = freight_svc.get_shipment_by_order(order_id)
    if not shipment:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(shipment)


@api.route("/shipments/<shipment_id>/tracking", methods=["POST"])
@require_auth("seller", "ops")
def add_tracking_event(shipment_id):
    data = request.get_json()
    if not data or "status" not in data:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "status required"}}), 400
    result = freight_svc.add_tracking_event(
        shipment_id, data["status"], data.get("description", ""),
        data.get("location_city"), data.get("location_state"), data.get("location_zip"),
    )
    if isinstance(result, dict) and "error" in result:
        return jsonify({"error": {"code": result["error"]}}), 404
    return jsonify(result), 201


@api.route("/shipments/<shipment_id>/tracking", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_tracking(shipment_id):
    events = freight_svc.get_tracking_events(shipment_id)
    return jsonify({"events": events})


# ════════════════════════════════════════
# INSPECTION + PAYOUT
# ════════════════════════════════════════

@api.route("/orders/<order_id>/inspect/accept", methods=["POST"])
@require_auth("buyer")
def accept_inspection(order_id):
    result = fulfillment_svc.accept_inspection(order_id, g.current_user_id)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "ORDER_NOT_FOUND":
            status = 404
        elif code == "NOT_AUTHORIZED":
            status = 403
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status
    return jsonify(result)


@api.route("/orders/<order_id>/payout", methods=["GET"])
@require_auth("seller", "ops")
def get_payout(order_id):
    payout = fulfillment_svc.get_payout_by_order(order_id)
    if not payout:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(payout)


# ════════════════════════════════════════
# DISPUTES
# ════════════════════════════════════════

@api.route("/disputes", methods=["POST"])
@require_auth("buyer")
def create_dispute():
    data = request.get_json()
    required = ["order_id", "type", "description", "claimed_amount_cents"]
    for field in required:
        if field not in data:
            return jsonify({"error": {"code": "MISSING_FIELD", "message": f"{field} required"}}), 400
    result = dispute_svc.create_dispute(g.current_user_id, data)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "ORDER_NOT_FOUND":
            status = 404
        elif code == "NOT_AUTHORIZED":
            status = 403
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status
    return jsonify(result), 201


@api.route("/disputes/<dispute_id>", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def get_dispute(dispute_id):
    dispute = dispute_svc.get_dispute(dispute_id)
    if not dispute:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(dispute)


@api.route("/disputes", methods=["GET"])
@require_auth("buyer", "seller", "ops")
def list_disputes():
    filters = {}
    if g.current_role == "buyer":
        filters["buyer_id"] = g.current_user_id
    elif g.current_role == "seller":
        filters["seller_id"] = g.current_user_id
    elif request.args.get("status"):
        filters["status"] = request.args.get("status")
    return jsonify({"disputes": dispute_svc.list_disputes(filters)})


@api.route("/disputes/<dispute_id>/respond", methods=["POST"])
@require_auth("seller")
def respond_to_dispute(dispute_id):
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": {"code": "MISSING_FIELD", "message": "message required"}}), 400
    result = dispute_svc.respond_to_dispute(dispute_id, g.current_user_id, data)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "DISPUTE_NOT_FOUND":
            status = 404
        elif code == "NOT_AUTHORIZED":
            status = 403
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status
    return jsonify(result)


@api.route("/disputes/<dispute_id>/evidence", methods=["POST"])
@require_auth("buyer", "seller")
def add_dispute_evidence(dispute_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "evidence data required"}}), 400
    result = dispute_svc.add_evidence(dispute_id, g.current_user_id, g.current_role, data)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "DISPUTE_NOT_FOUND":
            status = 404
        elif code == "NOT_AUTHORIZED":
            status = 403
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status
    return jsonify(result)


# ════════════════════════════════════════
# ADMIN / OPS
# ════════════════════════════════════════

@api.route("/admin/sellers/<seller_id>/verify", methods=["POST"])
@require_auth("ops")
def admin_verify_seller(seller_id):
    data = request.get_json()
    decision = data.get("decision", "APPROVED")
    seller = sellers.verify_seller(seller_id, decision, g.current_user_id)
    if not seller:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(seller)


@api.route("/admin/buyers/<buyer_id>/verify", methods=["POST"])
@require_auth("ops")
def admin_verify_buyer(buyer_id):
    data = request.get_json()
    decision = data.get("decision", "APPROVED")
    buyer = buyers.verify_buyer(buyer_id, decision, g.current_user_id)
    if not buyer:
        return jsonify({"error": {"code": "NOT_FOUND"}}), 404
    return jsonify(buyer)


@api.route("/admin/disputes/<dispute_id>/resolve", methods=["POST"])
@require_auth("ops")
def admin_resolve_dispute(dispute_id):
    data = request.get_json()
    required = ["resolution_type", "reasoning"]
    for field in required:
        if field not in data:
            return jsonify({"error": {"code": "MISSING_FIELD", "message": f"{field} required"}}), 400
    result = dispute_svc.resolve_dispute(dispute_id, g.current_user_id, data)
    if isinstance(result, dict) and "error" in result:
        code = result["error"]
        status = 400
        if code == "DISPUTE_NOT_FOUND":
            status = 404
        return jsonify({"error": {"code": code, "message": result.get("message", "")}}), status
    return jsonify(result)


@api.route("/admin/dashboard", methods=["GET"])
@require_auth("ops")
def admin_dashboard():
    from app.db import get_db
    with get_db() as conn:
        stats = {
            "sellers_total": conn.execute("SELECT COUNT(*) as c FROM sellers WHERE deleted_at IS NULL").fetchone()["c"],
            "sellers_active": conn.execute("SELECT COUNT(*) as c FROM sellers WHERE status = 'ACTIVE'").fetchone()["c"],
            "buyers_total": conn.execute("SELECT COUNT(*) as c FROM buyers WHERE deleted_at IS NULL").fetchone()["c"],
            "buyers_active": conn.execute("SELECT COUNT(*) as c FROM buyers WHERE status = 'ACTIVE'").fetchone()["c"],
            "lots_active": conn.execute("SELECT COUNT(*) as c FROM lots WHERE status = 'ACTIVE'").fetchone()["c"],
            "lots_sold": conn.execute("SELECT COUNT(*) as c FROM lots WHERE status = 'SOLD'").fetchone()["c"],
            "orders_total": conn.execute("SELECT COUNT(*) as c FROM orders").fetchone()["c"],
            "orders_completed": conn.execute("SELECT COUNT(*) as c FROM orders WHERE status = 'COMPLETED'").fetchone()["c"],
            "total_gmv_cents": conn.execute("SELECT COALESCE(SUM(lot_price_cents), 0) as s FROM orders").fetchone()["s"],
            "total_revenue_cents": conn.execute("SELECT COALESCE(SUM(platform_revenue_cents), 0) as s FROM orders").fetchone()["s"],
            "disputes_open": conn.execute("SELECT COUNT(*) as c FROM disputes WHERE status IN ('OPENED','SELLER_RESPONDED','UNDER_REVIEW')").fetchone()["c"],
            "offers_pending": conn.execute("SELECT COUNT(*) as c FROM offers WHERE status = 'PENDING'").fetchone()["c"],
        }
    return jsonify(stats)


# ════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════

def _int_param(name: str, default: int = None):
    val = request.args.get(name)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            return default
    return default
