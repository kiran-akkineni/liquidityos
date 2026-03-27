"""
End-to-end integration test — exercises the FULL order lifecycle via Flask test client.

Tests two complete paths:
  Path 1 (happy): register → lot → offer → escrow → ship → deliver → inspect → payout
  Path 2 (dispute): register → lot → offer → escrow → ship → deliver → dispute → resolve

Validates every HTTP status code and state transition.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use temp database for tests
TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["LIQUIDITYOS_DB_PATH"] = TEST_DB

from app.main import create_app
from app.db import init_db

passed = 0
failed = 0
errors = []


def ok(test_name):
    global passed
    passed += 1
    print(f"  ✓ {test_name}")


def fail(test_name, expected, got):
    global failed
    failed += 1
    msg = f"  ✗ {test_name}: expected {expected}, got {got}"
    errors.append(msg)
    print(msg)


def assert_status(resp, expected_code, test_name):
    if resp.status_code == expected_code:
        ok(f"{test_name} → {expected_code}")
    else:
        body = resp.get_data(as_text=True)[:200]
        fail(test_name, expected_code, f"{resp.status_code} ({body})")


def assert_field(data, field, expected, test_name):
    actual = data.get(field)
    if actual == expected:
        ok(f"{test_name}: {field}={expected}")
    else:
        fail(f"{test_name}: {field}", expected, actual)


def assert_in(data, field, test_name):
    if field in data and data[field] is not None:
        ok(f"{test_name}: has {field}")
    else:
        fail(f"{test_name}: has {field}", "present", "missing")


def run():
    global passed, failed

    app = create_app(init_database=False)
    app.config["TESTING"] = True

    with app.app_context():
        init_db()

    client = app.test_client()

    print("=" * 60)
    print("LiquidityOS End-to-End Integration Test")
    print("=" * 60)

    # ──────────────────────────────────────────────
    # 1. HEALTH CHECK
    # ──────────────────────────────────────────────
    print("\n1. Health check")
    r = client.get("/v1/health")
    assert_status(r, 200, "GET /v1/health")
    assert_field(r.get_json(), "status", "ok", "health")

    # ──────────────────────────────────────────────
    # 2. SELLER REGISTRATION + VERIFICATION
    # ──────────────────────────────────────────────
    print("\n2. Seller registration")
    r = client.post("/v1/sellers", json={
        "seller_type": "liquidator",
        "business_name": "TestSeller Inc",
        "primary_contact_name": "Test User",
        "primary_contact_email": "test@seller.com",
        "warehouse_locations": [{"location_id": "wh_01", "label": "Main",
            "address": {"city": "Dallas", "state": "TX", "zip": "75201"}}],
    })
    assert_status(r, 201, "POST /v1/sellers")
    seller_data = r.get_json()
    seller_id = seller_data["seller"]["seller_id"]
    seller_token = seller_data["token"]
    assert_in(seller_data["seller"], "seller_id", "seller registration")

    # Validate missing fields
    r = client.post("/v1/sellers", json={"business_name": "Incomplete"})
    assert_status(r, 400, "POST /v1/sellers missing fields")

    # Auth header helper
    def seller_h():
        return {"Authorization": f"Bearer {seller_token}"}

    # Get seller profile
    r = client.get("/v1/sellers/me", headers=seller_h())
    assert_status(r, 200, "GET /v1/sellers/me")
    assert_field(r.get_json(), "status", "PENDING_VERIFICATION", "seller status")

    # Verify seller (ops)
    ops_token_r = client.post("/v1/auth/token", json={"user_id": "ops_admin", "role": "ops"})
    ops_token = ops_token_r.get_json()["token"]
    def ops_h():
        return {"Authorization": f"Bearer {ops_token}"}

    r = client.post(f"/v1/admin/sellers/{seller_id}/verify", headers=ops_h(),
                     json={"decision": "APPROVED"})
    assert_status(r, 200, "POST /admin/sellers/verify")
    assert_field(r.get_json(), "status", "ACTIVE", "seller verified")

    # ──────────────────────────────────────────────
    # 3. BUYER REGISTRATION + VERIFICATION
    # ──────────────────────────────────────────────
    print("\n3. Buyer registration")
    r = client.post("/v1/buyers", json={
        "buyer_type": "ecom_reseller",
        "business_name": "TestBuyer LLC",
        "primary_contact_name": "Buyer User",
        "primary_contact_email": "test@buyer.com",
        "sales_channels": ["amazon_fba"],
    })
    assert_status(r, 201, "POST /v1/buyers")
    buyer_data = r.get_json()
    buyer_id = buyer_data["buyer"]["buyer_id"]
    buyer_token = buyer_data["token"]

    def buyer_h():
        return {"Authorization": f"Bearer {buyer_token}"}

    # Verify buyer
    r = client.post(f"/v1/admin/buyers/{buyer_id}/verify", headers=ops_h(),
                     json={"decision": "APPROVED"})
    assert_status(r, 200, "POST /admin/buyers/verify")

    # Create intent profile
    r = client.post("/v1/buyers/me/intent-profiles", headers=buyer_h(), json={
        "profile_name": "Test profile",
        "category_filters": {"include": ["electronics"]},
        "condition_min": "GOOD",
    })
    assert_status(r, 201, "POST /buyers/me/intent-profiles")
    profile_id = r.get_json()["profile_id"]

    # List profiles
    r = client.get("/v1/buyers/me/intent-profiles", headers=buyer_h())
    assert_status(r, 200, "GET /buyers/me/intent-profiles")

    # ──────────────────────────────────────────────
    # 4. LOT CREATION + ACTIVATION
    # ──────────────────────────────────────────────
    print("\n4. Lot creation")
    r = client.post("/v1/lots", headers=seller_h(), json={
        "title": "Test Lot — 50 units",
        "description": "Integration test lot",
        "total_units": 50, "total_skus": 15, "pallet_count": 1,
        "total_weight_lb": 500, "total_cube_cuft": 48,
        "estimated_retail_value_cents": 500000, "total_cost_cents": 80000,
        "condition_distribution": {"NEW": 0.80, "LIKE_NEW": 0.20},
        "condition_primary": "NEW",
        "category_primary": "electronics",
        "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas",
    })
    assert_status(r, 201, "POST /v1/lots")
    lot_id = r.get_json()["lot_id"]

    # Get lot
    r = client.get(f"/v1/lots/{lot_id}", headers=seller_h())
    assert_status(r, 200, "GET /v1/lots/<lot_id>")
    assert_field(r.get_json(), "status", "DRAFT", "lot is DRAFT")

    # Activate
    r = client.post(f"/v1/lots/{lot_id}/activate", headers=seller_h(), json={
        "ask_price_cents": 150000, "floor_price_cents": 120000, "mode": "MAKE_OFFER",
    })
    assert_status(r, 200, "POST /lots/<id>/activate")
    assert_field(r.get_json(), "status", "ACTIVE", "lot activated")

    # Missing ask_price_cents
    r = client.post(f"/v1/lots/{lot_id}/activate", headers=seller_h(), json={})
    assert_status(r, 400, "POST /lots/activate missing ask_price")

    # Search lots
    r = client.get("/v1/lots?categories=electronics", headers=buyer_h())
    assert_status(r, 200, "GET /v1/lots (search)")

    # ──────────────────────────────────────────────
    # 5. OFFER + NEGOTIATION → ORDER
    # ──────────────────────────────────────────────
    print("\n5. Offer + negotiation")

    # Offer below floor
    r = client.post("/v1/offers", headers=buyer_h(), json={
        "lot_id": lot_id, "offered_price_cents": 50000, "offer_type": "MAKE_OFFER",
    })
    assert_status(r, 400, "POST /v1/offers below floor")

    # Valid offer
    r = client.post("/v1/offers", headers=buyer_h(), json={
        "lot_id": lot_id, "offered_price_cents": 125000, "offer_type": "MAKE_OFFER",
        "message": "Fair offer for test lot.",
    })
    assert_status(r, 201, "POST /v1/offers")
    offer_id = r.get_json()["offer_id"]

    # Get offer
    r = client.get(f"/v1/offers/{offer_id}", headers=buyer_h())
    assert_status(r, 200, "GET /v1/offers/<id>")
    assert_field(r.get_json(), "status", "PENDING", "offer PENDING")

    # Seller counters
    r = client.post(f"/v1/offers/{offer_id}/counter", headers=seller_h(), json={
        "counter_price_cents": 140000, "message": "How about $1,400?",
    })
    assert_status(r, 200, "POST /offers/<id>/counter")
    counter_id = r.get_json()["counter"]["counter_id"]

    # Missing counter_price_cents
    r = client.post(f"/v1/offers/{offer_id}/counter", headers=seller_h(), json={})
    assert_status(r, 400, "POST /offers/counter missing field")

    # Buyer accepts counter → order created
    r = client.post(f"/v1/counters/{counter_id}/accept", headers=buyer_h())
    assert_status(r, 200, "POST /counters/<id>/accept")
    result = r.get_json()
    order = result["order"]
    order_id = order["order_id"]
    assert_field(order, "status", "AWAITING_PAYMENT", "order AWAITING_PAYMENT")
    assert_in(order, "escrow_id", "order has escrow_id")

    # ──────────────────────────────────────────────
    # 6. ESCROW + PAYMENT
    # ──────────────────────────────────────────────
    print("\n6. Escrow + payment")

    # Get escrow
    r = client.get(f"/v1/orders/{order_id}/escrow", headers=buyer_h())
    assert_status(r, 200, "GET /orders/<id>/escrow")
    assert_field(r.get_json(), "status", "PENDING_FUNDING", "escrow PENDING_FUNDING")

    # Fund escrow
    r = client.post(f"/v1/orders/{order_id}/escrow/fund", headers=buyer_h(), json={
        "method": "card", "reference": "tok_test_1234",
    })
    assert_status(r, 200, "POST /orders/<id>/escrow/fund")
    assert_field(r.get_json(), "status", "FUNDED", "escrow FUNDED")

    # Verify order transitioned
    r = client.get(f"/v1/orders/{order_id}", headers=buyer_h())
    assert_field(r.get_json(), "status", "AWAITING_SHIPMENT", "order AWAITING_SHIPMENT")

    # Double-fund should fail
    r = client.post(f"/v1/orders/{order_id}/escrow/fund", headers=buyer_h(), json={})
    assert_status(r, 400, "POST /escrow/fund double-fund rejected")

    # Invoices generated
    r = client.get(f"/v1/orders/{order_id}/invoices", headers=buyer_h())
    assert_status(r, 200, "GET /orders/<id>/invoices")
    invoices = r.get_json()["invoices"]
    if len(invoices) == 2:
        ok("2 invoices generated (buyer + seller)")
    else:
        fail("invoice count", 2, len(invoices))

    # ──────────────────────────────────────────────
    # 7. FREIGHT QUOTE + SHIPMENT BOOKING
    # ──────────────────────────────────────────────
    print("\n7. Freight + shipment")

    # Get freight quote
    r = client.post(f"/v1/lots/{lot_id}/freight-quotes", headers=buyer_h(), json={
        "destination_zip": "75201",
    })
    assert_status(r, 201, "POST /lots/<id>/freight-quotes")
    quote = r.get_json()
    quote_id = quote["quote_id"]
    options = quote["options"]
    if len(options) >= 2:
        ok(f"freight quote has {len(options)} options")
    else:
        fail("freight options count", ">=2", len(options))

    # Missing destination_zip
    r = client.post(f"/v1/lots/{lot_id}/freight-quotes", headers=buyer_h(), json={})
    assert_status(r, 400, "POST /freight-quotes missing destination_zip")

    # Book shipment
    r = client.post(f"/v1/orders/{order_id}/shipment/book", headers=seller_h(), json={
        "quote_id": quote_id, "selected_option_index": 0,
    })
    assert_status(r, 201, "POST /orders/<id>/shipment/book")
    shipment = r.get_json()
    shipment_id = shipment["shipment_id"]
    assert_field(shipment, "status", "BOOKED", "shipment BOOKED")
    assert_in(shipment, "tracking_number", "shipment has tracking")

    # Get shipment
    r = client.get(f"/v1/orders/{order_id}/shipment", headers=buyer_h())
    assert_status(r, 200, "GET /orders/<id>/shipment")

    # ──────────────────────────────────────────────
    # 8. TRACKING + DELIVERY
    # ──────────────────────────────────────────────
    print("\n8. Tracking + delivery")

    # Add tracking: PICKED_UP
    r = client.post(f"/v1/shipments/{shipment_id}/tracking", headers=seller_h(), json={
        "status": "PICKED_UP", "description": "Picked up from seller",
        "location_city": "Dallas", "location_state": "TX",
    })
    assert_status(r, 201, "POST tracking PICKED_UP")

    # Update order to SHIPPED
    from app.services.freight import update_order_shipped
    with app.app_context():
        update_order_shipped(order_id)
    r = client.get(f"/v1/orders/{order_id}", headers=buyer_h())
    assert_field(r.get_json(), "status", "SHIPPED", "order SHIPPED")

    # IN_TRANSIT
    r = client.post(f"/v1/shipments/{shipment_id}/tracking", headers=seller_h(), json={
        "status": "IN_TRANSIT", "description": "In transit",
    })
    assert_status(r, 201, "POST tracking IN_TRANSIT")

    # DELIVERED → triggers inspection window
    r = client.post(f"/v1/shipments/{shipment_id}/tracking", headers=seller_h(), json={
        "status": "DELIVERED", "description": "Delivered to buyer",
        "location_city": "Dallas", "location_state": "TX", "location_zip": "75201",
    })
    assert_status(r, 201, "POST tracking DELIVERED")

    # Order should be INSPECTION
    r = client.get(f"/v1/orders/{order_id}", headers=buyer_h())
    order_data = r.get_json()
    assert_field(order_data, "status", "INSPECTION", "order INSPECTION")
    assert_in(order_data, "inspection_window_closes_at", "inspection window set")

    # Get tracking events
    r = client.get(f"/v1/shipments/{shipment_id}/tracking", headers=buyer_h())
    assert_status(r, 200, "GET /shipments/<id>/tracking")
    events = r.get_json()["events"]
    if len(events) == 3:
        ok("3 tracking events recorded")
    else:
        fail("tracking events count", 3, len(events))

    # ──────────────────────────────────────────────
    # 9. INSPECTION + PAYOUT
    # ──────────────────────────────────────────────
    print("\n9. Inspection + payout")

    # Accept inspection
    r = client.post(f"/v1/orders/{order_id}/inspect/accept", headers=buyer_h())
    assert_status(r, 200, "POST /orders/<id>/inspect/accept")
    result = r.get_json()
    assert_field(result, "order_status", "COMPLETED", "order COMPLETED")
    assert_field(result, "inspection_result", "ACCEPTED", "inspection ACCEPTED")
    assert_in(result, "payout", "payout initiated")

    payout = result["payout"]
    assert_field(payout, "status", "INITIATED", "payout INITIATED")
    if payout["amount_cents"] > 0:
        ok(f"payout amount: {payout['amount_cents']} cents")
    else:
        fail("payout amount", ">0", payout["amount_cents"])

    # Get payout
    r = client.get(f"/v1/orders/{order_id}/payout", headers=seller_h())
    assert_status(r, 200, "GET /orders/<id>/payout")

    # Verify escrow released
    r = client.get(f"/v1/orders/{order_id}/escrow", headers=buyer_h())
    assert_field(r.get_json(), "status", "RELEASED", "escrow RELEASED")

    # Verify order final state
    r = client.get(f"/v1/orders/{order_id}", headers=buyer_h())
    final_order = r.get_json()
    assert_field(final_order, "status", "COMPLETED", "final order COMPLETED")
    assert_in(final_order, "completed_at", "completed_at set")

    # Double-accept should fail
    r = client.post(f"/v1/orders/{order_id}/inspect/accept", headers=buyer_h())
    assert_status(r, 400, "POST inspect/accept on completed order rejected")

    print("\n" + "─" * 60)
    print("PATH 1 COMPLETE: Happy path ✓")
    print("─" * 60)

    # ══════════════════════════════════════════════
    # PATH 2: DISPUTE FLOW
    # ══════════════════════════════════════════════
    print("\n10. Dispute flow — new lot")

    # Create + activate lot 2
    r = client.post("/v1/lots", headers=seller_h(), json={
        "title": "Test Lot 2 — for dispute", "total_units": 30,
        "total_skus": 10, "pallet_count": 1, "total_weight_lb": 300,
        "total_cube_cuft": 24, "estimated_retail_value_cents": 300000,
        "total_cost_cents": 50000,
        "condition_distribution": {"NEW": 0.70, "GOOD": 0.30},
        "condition_primary": "NEW", "category_primary": "electronics",
        "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas",
    })
    lot2_id = r.get_json()["lot_id"]

    r = client.post(f"/v1/lots/{lot2_id}/activate", headers=seller_h(), json={
        "ask_price_cents": 100000, "floor_price_cents": 80000,
    })
    assert_status(r, 200, "lot 2 activated")

    # Buy at ask price (ACCEPT_ASK)
    r = client.post("/v1/offers", headers=buyer_h(), json={
        "lot_id": lot2_id, "offered_price_cents": 100000, "offer_type": "ACCEPT_ASK",
    })
    assert_status(r, 201, "offer ACCEPT_ASK")
    order2 = r.get_json()["order"]
    order2_id = order2["order_id"]

    # Fund escrow
    r = client.post(f"/v1/orders/{order2_id}/escrow/fund", headers=buyer_h(), json={
        "method": "ach",
    })
    assert_status(r, 200, "escrow 2 funded")

    # Ship + deliver
    quote2_r = client.post(f"/v1/lots/{lot2_id}/freight-quotes", headers=buyer_h(),
                            json={"destination_zip": "75201"})
    quote2_id = quote2_r.get_json()["quote_id"]
    ship2_r = client.post(f"/v1/orders/{order2_id}/shipment/book", headers=seller_h(),
                           json={"quote_id": quote2_id})
    ship2_id = ship2_r.get_json()["shipment_id"]

    client.post(f"/v1/shipments/{ship2_id}/tracking", headers=seller_h(),
                json={"status": "PICKED_UP", "description": "Picked up"})
    with app.app_context():
        update_order_shipped(order2_id)
    client.post(f"/v1/shipments/{ship2_id}/tracking", headers=seller_h(),
                json={"status": "DELIVERED", "description": "Delivered"})

    r = client.get(f"/v1/orders/{order2_id}", headers=buyer_h())
    assert_field(r.get_json(), "status", "INSPECTION", "order 2 INSPECTION")

    # ──────────────────────────────────────────────
    # 11. FILE DISPUTE
    # ──────────────────────────────────────────────
    print("\n11. Dispute creation")

    r = client.post("/v1/disputes", headers=buyer_h(), json={
        "order_id": order2_id,
        "type": "CONDITION_MISMATCH",
        "description": "10 units listed as NEW are clearly used.",
        "affected_units": 10,
        "total_units": 30,
        "claimed_amount_cents": 30000,
        "evidence": [{"type": "photo", "url": "s3://test/evidence.jpg"}],
    })
    assert_status(r, 201, "POST /v1/disputes")
    dispute = r.get_json()
    dispute_id = dispute["dispute_id"]
    assert_field(dispute, "status", "OPENED", "dispute OPENED")

    # Order should be DISPUTED
    r = client.get(f"/v1/orders/{order2_id}", headers=buyer_h())
    assert_field(r.get_json(), "status", "DISPUTED", "order DISPUTED")

    # Escrow should be HELD
    r = client.get(f"/v1/orders/{order2_id}/escrow", headers=buyer_h())
    assert_field(r.get_json(), "status", "HELD", "escrow HELD")

    # Get dispute
    r = client.get(f"/v1/disputes/{dispute_id}", headers=buyer_h())
    assert_status(r, 200, "GET /disputes/<id>")

    # List disputes
    r = client.get("/v1/disputes", headers=buyer_h())
    assert_status(r, 200, "GET /disputes (buyer)")
    r = client.get("/v1/disputes", headers=seller_h())
    assert_status(r, 200, "GET /disputes (seller)")

    # Validate missing fields
    r = client.post("/v1/disputes", headers=buyer_h(), json={"order_id": order2_id})
    assert_status(r, 400, "POST /disputes missing fields")

    # ──────────────────────────────────────────────
    # 12. SELLER RESPONSE
    # ──────────────────────────────────────────────
    print("\n12. Seller response")

    r = client.post(f"/v1/disputes/{dispute_id}/respond", headers=seller_h(), json={
        "message": "We can offer a partial refund.",
        "proposed_resolution": "PARTIAL_REFUND",
        "proposed_refund_cents": 20000,
        "evidence": [{"type": "document", "url": "s3://test/qa_report.pdf"}],
    })
    assert_status(r, 200, "POST /disputes/<id>/respond")
    assert_field(r.get_json(), "status", "SELLER_RESPONDED", "dispute SELLER_RESPONDED")

    # Double-respond should fail
    r = client.post(f"/v1/disputes/{dispute_id}/respond", headers=seller_h(), json={
        "message": "Another response",
    })
    assert_status(r, 400, "POST /disputes/respond on non-OPENED rejected")

    # ──────────────────────────────────────────────
    # 13. ADD EVIDENCE
    # ──────────────────────────────────────────────
    print("\n13. Add evidence")

    r = client.post(f"/v1/disputes/{dispute_id}/evidence", headers=buyer_h(), json={
        "type": "video", "url": "s3://test/unboxing.mp4", "description": "Unboxing video",
    })
    assert_status(r, 200, "POST /disputes/<id>/evidence (buyer)")

    r = client.post(f"/v1/disputes/{dispute_id}/evidence", headers=seller_h(), json={
        "type": "document", "url": "s3://test/shipping_manifest.pdf",
    })
    assert_status(r, 200, "POST /disputes/<id>/evidence (seller)")

    # ──────────────────────────────────────────────
    # 14. OPS RESOLUTION
    # ──────────────────────────────────────────────
    print("\n14. Ops resolution")

    # Missing fields
    r = client.post(f"/v1/admin/disputes/{dispute_id}/resolve", headers=ops_h(), json={})
    assert_status(r, 400, "POST /admin/disputes/resolve missing fields")

    r = client.post(f"/v1/admin/disputes/{dispute_id}/resolve", headers=ops_h(), json={
        "resolution_type": "PARTIAL_REFUND",
        "refund_amount_cents": 25000,
        "reasoning": "Evidence supports mislabeled condition on 10 units.",
    })
    assert_status(r, 200, "POST /admin/disputes/<id>/resolve")
    result = r.get_json()
    assert_field(result["dispute"], "status", "RESOLVED", "dispute RESOLVED")
    assert_field(result["resolution"], "resolution_type", "PARTIAL_REFUND", "resolution type")
    assert_field(result["resolution"], "refund_amount_cents", 25000, "refund amount")

    # Escrow should be PARTIALLY_RELEASED
    r = client.get(f"/v1/orders/{order2_id}/escrow", headers=buyer_h())
    assert_field(r.get_json(), "status", "PARTIALLY_RELEASED", "escrow PARTIALLY_RELEASED")

    # Double-resolve should fail
    r = client.post(f"/v1/admin/disputes/{dispute_id}/resolve", headers=ops_h(), json={
        "resolution_type": "NO_REFUND", "reasoning": "trying again",
    })
    assert_status(r, 400, "POST /admin/disputes/resolve on resolved rejected")

    # ──────────────────────────────────────────────
    # 15. ADMIN DASHBOARD
    # ──────────────────────────────────────────────
    print("\n15. Admin dashboard")

    r = client.get("/v1/admin/dashboard", headers=ops_h())
    assert_status(r, 200, "GET /admin/dashboard")
    dash = r.get_json()
    if dash["orders_total"] == 2:
        ok(f"dashboard: 2 orders")
    else:
        fail("dashboard orders_total", 2, dash["orders_total"])
    if dash["orders_completed"] == 1:
        ok("dashboard: 1 completed order")
    else:
        fail("dashboard orders_completed", 1, dash["orders_completed"])
    if dash["total_gmv_cents"] > 0:
        ok(f"dashboard: GMV = {dash['total_gmv_cents']} cents")
    else:
        fail("dashboard GMV", ">0", dash["total_gmv_cents"])

    # ──────────────────────────────────────────────
    # 16. AUTH EDGE CASES
    # ──────────────────────────────────────────────
    print("\n16. Auth edge cases")

    # No token
    r = client.get("/v1/sellers/me")
    assert_status(r, 401, "GET /sellers/me without token")

    # Wrong role
    r = client.post("/v1/lots", headers=buyer_h(), json={"title": "should fail"})
    assert_status(r, 403, "POST /lots with buyer token (seller-only)")

    # Invalid token
    r = client.get("/v1/sellers/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert_status(r, 401, "GET /sellers/me with invalid token")

    # 404 on nonexistent resources
    r = client.get("/v1/lots/lot_doesnotexist", headers=buyer_h())
    assert_status(r, 404, "GET /lots/<nonexistent>")

    r = client.get("/v1/orders/ord_doesnotexist", headers=buyer_h())
    assert_status(r, 404, "GET /orders/<nonexistent>")

    r = client.get("/v1/disputes/dsp_doesnotexist", headers=buyer_h())
    assert_status(r, 404, "GET /disputes/<nonexistent>")

    # ──────────────────────────────────────────────
    # 17. LIST ENDPOINTS
    # ──────────────────────────────────────────────
    print("\n17. List endpoints")

    r = client.get("/v1/orders", headers=buyer_h())
    assert_status(r, 200, "GET /orders (buyer)")
    if len(r.get_json()["orders"]) == 2:
        ok("buyer sees 2 orders")
    else:
        fail("buyer order count", 2, len(r.get_json()["orders"]))

    r = client.get("/v1/orders", headers=seller_h())
    assert_status(r, 200, "GET /orders (seller)")

    r = client.get("/v1/orders?status=COMPLETED", headers=buyer_h())
    assert_status(r, 200, "GET /orders?status=COMPLETED")
    if len(r.get_json()["orders"]) == 1:
        ok("1 completed order")
    else:
        fail("completed order count", 1, len(r.get_json()["orders"]))

    r = client.get("/v1/disputes", headers=ops_h())
    assert_status(r, 200, "GET /disputes (ops)")

    # ══════════════════════════════════════════════
    # RESULTS
    # ══════════════════════════════════════════════
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(e)
    print("=" * 60)

    # Cleanup
    try:
        os.unlink(TEST_DB)
    except OSError:
        pass

    return failed == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
