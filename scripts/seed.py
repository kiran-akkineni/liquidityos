"""
Seed script — populates the database with realistic test data
that traces one complete transaction end-to-end.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import init_db
from app.db import get_db as db_conn
from app.utils.helpers import make_id, now_iso, json_dumps
from app.services import sellers, buyers, lots, pricing, offers
from app.services import escrow as escrow_svc, invoices as invoice_svc
from app.services import freight as freight_svc, fulfillment as fulfillment_svc
from app.services import disputes as dispute_svc


def seed():
    print("Initializing database...")
    init_db()

    print("\n1. Registering seller: PalletPros LLC...")
    seller = sellers.register_seller({
        "seller_type": "liquidator",
        "business_name": "PalletPros LLC",
        "dba_name": "PalletPros",
        "ein_tin": "12-3456789",
        "state_of_incorporation": "TX",
        "primary_contact_name": "Mike Rodriguez",
        "primary_contact_email": "mike@palletpros.com",
        "primary_contact_phone": "+14155551234",
        "warehouse_locations": [{
            "location_id": "wh_001",
            "label": "Main Warehouse",
            "address": {"street": "1234 Distribution Dr", "city": "Dallas", "state": "TX", "zip": "75201"},
            "capabilities": {"has_dock": True, "has_forklift": True},
            "is_primary": True,
        }],
        "estimated_monthly_volume_cents": 5000000,
        "estimated_monthly_pallets": 40,
    })
    seller_id = seller["seller_id"]
    print(f"   → Seller ID: {seller_id}")

    # Verify seller (ops action)
    print("   → Verifying seller...")
    sellers.verify_seller(seller_id, "APPROVED", "ops_admin")

    print("\n2. Registering buyer: FlipKing Ventures LLC...")
    buyer = buyers.register_buyer({
        "buyer_type": "ecom_reseller",
        "business_name": "FlipKing Ventures LLC",
        "ein_tin": "98-7654321",
        "primary_contact_name": "Sarah Chen",
        "primary_contact_email": "sarah@flipking.com",
        "primary_contact_phone": "+12145559876",
        "sales_channels": ["amazon_fba", "ebay"],
        "primary_channel": "amazon_fba",
        "warehouses": [{
            "warehouse_id": "bwh_001",
            "label": "Main Receiving",
            "address": {"street": "5678 Commerce Blvd", "city": "Dallas", "state": "TX", "zip": "75201"},
            "capabilities": {"has_dock": True, "appointment_required": True, "max_pallet_count": 8},
            "is_primary": True,
        }],
        "estimated_monthly_volume_cents": 2000000,
    })
    buyer_id = buyer["buyer_id"]
    print(f"   → Buyer ID: {buyer_id}")

    # Verify buyer
    print("   → Verifying buyer...")
    buyers.verify_buyer(buyer_id, "APPROVED", "ops_admin")

    print("\n3. Creating buyer intent profile...")
    profile = buyers.create_intent_profile(buyer_id, {
        "profile_name": "Main sourcing profile",
        "category_filters": {"include": ["home_kitchen", "toys", "sporting_goods"], "exclude": ["apparel"]},
        "brand_filters": {"preferred": ["KitchenAid", "Instant Pot", "Ninja"], "excluded": ["Generic"]},
        "condition_min": "GOOD",
        "channel_config": {"channels": ["amazon_fba", "ebay"], "primary_margin_channel": "amazon_fba"},
        "economics": {"margin_target_pct": 35, "max_turn_days": 45, "max_lot_cost_cents": 500000},
        "logistics": {"destination_zip": "75201", "max_freight_cost_pct": 15},
        "trust_filters": {"min_seller_reputation": 70},
    })
    print(f"   → Profile ID: {profile['profile_id']}")

    print("\n4. Seeding canonical products...")
    ts = now_iso()
    products = [
        {"product_id": make_id("cprod_"), "upc": "012345678901", "asin": "B08N5WRWNW",
         "title": "Instant Pot Duo 7-in-1, 6 Quart", "brand_normalized": "Instant Pot",
         "department": "Home & Kitchen", "category_l1": "Kitchen & Dining", "category_l2": "Small Appliances",
         "retail_price_cents": 8999, "msrp_cents": 8999,
         "resale_data": {"amazon_fba": {"current_listing_price_cents": 7499, "avg_sell_through_days": 14}},
         },
        {"product_id": make_id("cprod_"), "upc": "012345678902", "asin": "B07S85TPLG",
         "title": "Ninja Professional Blender, 72oz", "brand_normalized": "Ninja",
         "department": "Home & Kitchen", "category_l1": "Kitchen & Dining", "category_l2": "Small Appliances",
         "retail_price_cents": 6999, "msrp_cents": 6999,
         "resale_data": {"amazon_fba": {"current_listing_price_cents": 5999, "avg_sell_through_days": 18}},
         },
        {"product_id": make_id("cprod_"), "upc": "012345678903", "asin": "B09KZ26N23",
         "title": "KitchenAid Hand Mixer, 5-Speed", "brand_normalized": "KitchenAid",
         "department": "Home & Kitchen", "category_l1": "Kitchen & Dining", "category_l2": "Small Appliances",
         "retail_price_cents": 5499, "msrp_cents": 5499,
         "resale_data": {"amazon_fba": {"current_listing_price_cents": 4999, "avg_sell_through_days": 21}},
         },
    ]

    with db_conn() as conn:
        for p in products:
            conn.execute(
                """INSERT INTO canonical_products
                   (product_id, upc, asin, title, brand_normalized, department,
                    category_l1, category_l2, retail_price_cents, msrp_cents,
                    resale_data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (p["product_id"], p["upc"], p["asin"], p["title"], p["brand_normalized"],
                 p["department"], p["category_l1"], p["category_l2"],
                 p["retail_price_cents"], p["msrp_cents"],
                 json_dumps(p["resale_data"]), ts, ts)
            )
    print(f"   → Seeded {len(products)} canonical products")

    print("\n5. Creating lot: Mixed Home & Kitchen...")
    lot = lots.create_lot(seller_id, {
        "title": "Mixed Home & Kitchen – 127 units, 2 pallets",
        "description": "Customer return lot. Mix of small kitchen appliances and home goods. 65% new, 30% like new, 5% good.",
        "total_units": 127,
        "total_skus": 42,
        "total_weight_lb": 1840,
        "total_cube_cuft": 96,
        "pallet_count": 2,
        "packing_type": "pallet",
        "estimated_retail_value_cents": 1240000,
        "total_cost_cents": 180000,
        "condition_distribution": {"NEW": 0.65, "LIKE_NEW": 0.30, "GOOD": 0.05},
        "condition_primary": "NEW",
        "category_primary": "home_kitchen",
        "categories": {"primary": "home_kitchen", "secondary": ["small_appliances"], "department": "Home & Kitchen"},
        "top_brands": ["Instant Pot", "Ninja", "KitchenAid", "OXO"],
        "ship_from_zip": "75201",
        "ship_from_state": "TX",
        "ship_from_city": "Dallas",
        "ship_from_location_id": "wh_001",
        "media": {"photos": [
            {"url": "s3://liquidityos-media/lot/photo_001.jpg", "type": "overview"},
            {"url": "s3://liquidityos-media/lot/photo_002.jpg", "type": "label_detail"},
            {"url": "s3://liquidityos-media/lot/photo_003.jpg", "type": "pallet_detail"},
        ]},
    })
    lot_id = lot["lot_id"]
    print(f"   → Lot ID: {lot_id} (status: DRAFT)")

    # Seed some normalized line items for the lot
    with db_conn() as conn:
        # Create a stub ingestion job for FK references
        conn.execute(
            """INSERT INTO ingestion_jobs (job_id, seller_id, file_key, file_name, file_type, status, created_at)
               VALUES ('mfst_seed', ?, 's3://seed/manifest.xlsx', 'seed_manifest.xlsx', 'xlsx', 'COMPLETED', ?)""",
            (seller_id, ts)
        )
        for i, p in enumerate(products):
            nli_id = make_id("nli_")
            rli_id = make_id("rli_")
            qty = [3, 5, 4][i]

            conn.execute(
                """INSERT INTO raw_line_items (raw_item_id, job_id, row_number, raw_fields, created_at)
                   VALUES (?, 'mfst_seed', ?, '{}', ?)""",
                (rli_id, i + 1, ts)
            )

            conn.execute(
                """INSERT INTO normalized_line_items
                   (normalized_item_id, raw_item_id, job_id, lot_id, product_id,
                    match_type, match_confidence, title, brand_normalized,
                    category_l1, condition_grade, quantity, unit_cost_cents,
                    total_cost_cents, retail_price_cents, created_at, updated_at)
                   VALUES (?, ?, 'mfst_seed', ?, ?, 'EXACT', 0.98, ?, ?, ?, 'LIKE_NEW', ?, ?, ?, ?, ?, ?)""",
                (nli_id, rli_id, lot_id, p["product_id"], p["title"], p["brand_normalized"],
                 p["category_l1"], qty, p["retail_price_cents"] // 4,
                 (p["retail_price_cents"] // 4) * qty, p["retail_price_cents"], ts, ts)
            )

            lli_id = make_id("lli_")
            conn.execute(
                """INSERT INTO lot_line_items
                   (lot_line_item_id, lot_id, normalized_item_id, product_id,
                    quantity, condition_grade, unit_cost_cents, retail_price_cents,
                    brand_normalized, category_l1, sort_order, created_at)
                   VALUES (?, ?, ?, ?, ?, 'LIKE_NEW', ?, ?, ?, ?, ?, ?)""",
                (lli_id, lot_id, nli_id, p["product_id"],
                 qty, p["retail_price_cents"] // 4, p["retail_price_cents"],
                 p["brand_normalized"], p["category_l1"], i, ts)
            )
    print("   → Seeded line items for lot")

    print("\n6. Activating lot with pricing...")
    lot = lots.activate_lot(lot_id, seller_id, {
        "mode": "MAKE_OFFER",
        "ask_price_cents": 280000,
        "floor_price_cents": 220000,
    })
    print(f"   → Lot status: {lot['status']}, ask: ${lot['ask_price_cents']/100:,.0f}")

    print("\n7. Computing margin simulation for buyer...")
    sim = pricing.compute_margin_simulation(
        lot_id, buyer_id, "amazon_fba", "75201", 260000
    )
    print(f"   → Estimated margin: {sim['margin_analysis']['margin_pct']}%")
    print(f"   → Estimated profit: ${sim['margin_analysis']['estimated_gross_profit_cents']/100:,.0f}")

    print("\n8. Buyer places offer at $2,400...")
    offer_result = offers.create_offer(buyer_id, {
        "lot_id": lot_id,
        "offer_type": "MAKE_OFFER",
        "offered_price_cents": 240000,
        "message": "Happy to close quickly.",
    })
    if "error" in offer_result:
        print(f"   → Error: {offer_result['error']}")
        return
    offer_id = offer_result["offer_id"]
    print(f"   → Offer ID: {offer_id} (status: {offer_result['status']})")

    print("\n9. Seller counters at $2,600...")
    counter_result = offers.counter_offer(offer_id, seller_id, 260000, "Can do $2,600 — mostly new condition.")
    counter_id = counter_result["counter"]["counter_id"]
    print(f"   → Counter ID: {counter_id}")

    print("\n10. Buyer accepts counter-offer...")
    accept_result = offers.accept_counter(counter_id, buyer_id)
    order = accept_result["order"]
    print(f"   → Order ID: {order['order_id']}")
    print(f"   → Order status: {order['status']}")
    print(f"   → Total buyer cost: ${order['total_buyer_cost_cents']/100:,.2f}")
    print(f"   → Seller payout: ${order['seller_payout_cents']/100:,.2f}")
    print(f"   → Platform revenue: ${order['platform_revenue_cents']/100:,.2f}")

    # ── Week 9: Escrow + Payment ──

    order_id = order["order_id"]

    print("\n11. Checking escrow created with order...")
    esc = escrow_svc.get_escrow_by_order(order_id)
    print(f"   → Escrow ID: {esc['escrow_id']}")
    print(f"   → Status: {esc['status']}")
    print(f"   → Total: ${esc['total_cents']/100:,.2f}")
    print(f"   → Funding deadline: {esc['funding_deadline']}")

    print("\n12. Buyer funds escrow...")
    funded = escrow_svc.fund_escrow(order_id, buyer_id, {
        "method": "card",
        "reference": "tok_visa_4242",
        "processor_txn_id": "pi_test_123456",
    })
    print(f"   → Escrow status: {funded['status']}")
    print(f"   → Funded at: {funded['funded_at']}")

    # Verify order transitioned
    with db_conn() as conn:
        updated_order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    print(f"   → Order status: {updated_order['status']}")

    print("\n13. Generating invoices...")
    from app.db import dict_from_row
    order_dict = dict_from_row(updated_order)
    invs = invoice_svc.generate_invoices(order_dict)
    buyer_inv = invs["buyer_invoice"]
    seller_inv = invs["seller_invoice"]
    print(f"   → Buyer invoice: {buyer_inv['invoice_id']} — ${buyer_inv['total_cents']/100:,.2f}")
    print(f"   → Seller invoice: {seller_inv['invoice_id']} — ${seller_inv['total_cents']/100:,.2f}")

    # ── Week 10: Freight + Delivery + Payout ──

    print("\n14. Getting freight quotes...")
    quote = freight_svc.get_freight_quote(lot_id, "75201", buyer_id)
    options = quote["options"]
    print(f"   → Quote ID: {quote['quote_id']}")
    for i, opt in enumerate(options):
        print(f"   → Option {i}: {opt['carrier_name']} — ${opt['cost_cents']/100:,.2f} ({opt['transit_days']}d)")

    print("\n15. Booking shipment (cheapest option)...")
    shipment = freight_svc.book_shipment(order_id, quote["quote_id"], 0)
    shipment_id = shipment["shipment_id"]
    print(f"   → Shipment ID: {shipment_id}")
    print(f"   → Carrier: {shipment['carrier_name']}")
    print(f"   → Tracking: {shipment['tracking_number']}")
    print(f"   → Status: {shipment['status']}")

    print("\n16. Simulating shipment lifecycle...")
    # Picked up
    freight_svc.add_tracking_event(shipment_id, "PICKED_UP", "Picked up from origin facility",
                                    "Dallas", "TX", "75201")
    freight_svc.update_order_shipped(order_id)
    print("   → PICKED_UP — order status: SHIPPED")

    # In transit
    freight_svc.add_tracking_event(shipment_id, "IN_TRANSIT", "In transit to destination",
                                    "Fort Worth", "TX", "76102")
    print("   → IN_TRANSIT")

    # Out for delivery
    freight_svc.add_tracking_event(shipment_id, "OUT_FOR_DELIVERY", "Out for delivery",
                                    "Dallas", "TX", "75201")
    print("   → OUT_FOR_DELIVERY")

    # Delivered (triggers inspection window)
    result = freight_svc.add_tracking_event(shipment_id, "DELIVERED",
                                             "Delivered — signed by S. Chen",
                                             "Dallas", "TX", "75201")
    print("   → DELIVERED — inspection window opened (48h)")

    # Verify order is in INSPECTION status
    with db_conn() as conn:
        insp_order = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone())
    print(f"   → Order status: {insp_order['status']}")
    print(f"   → Inspection closes: {insp_order['inspection_window_closes_at']}")

    print("\n17. Buyer accepts inspection...")
    accept_result = fulfillment_svc.accept_inspection(order_id, buyer_id)
    print(f"   → Order status: {accept_result['order_status']}")
    print(f"   → Inspection result: {accept_result['inspection_result']}")

    payout = accept_result["payout"]
    print(f"   → Payout ID: {payout['payout_id']}")
    print(f"   → Payout amount: ${payout['amount_cents']/100:,.2f}")
    print(f"   → Payout status: {payout['status']}")
    print(f"   → Expected arrival: {payout['expected_arrival_date']}")

    # Verify reputation events
    with db_conn() as conn:
        rep_count = conn.execute("SELECT COUNT(*) as c FROM reputation_events").fetchone()["c"]
        seller_score = conn.execute("SELECT quality_score FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()["quality_score"]
        buyer_score = conn.execute("SELECT trust_score FROM buyers WHERE buyer_id = ?", (buyer_id,)).fetchone()["trust_score"]
    print(f"\n18. Reputation updated:")
    print(f"   → Seller quality_score: {seller_score} (+2)")
    print(f"   → Buyer trust_score: {buyer_score} (+2)")
    print(f"   → Reputation events: {rep_count}")

    # Verify escrow released
    final_escrow = escrow_svc.get_escrow_by_order(order_id)
    print(f"\n19. Escrow status: {final_escrow['status']}")

    # Verify lot sold
    final_lot = lots.get_lot(lot_id)
    print(f"   → Lot status: {final_lot['status']}")

    # ══════════════════════════════════════════════════════════
    # TRANSACTION 2: Dispute Flow
    # ══════════════════════════════════════════════════════════

    print("\n" + "=" * 60)
    print("TRANSACTION 2: Dispute scenario")
    print("=" * 60)

    print("\n20. Creating second lot...")
    lot2 = lots.create_lot(seller_id, {
        "title": "Mixed Electronics – 85 units, 1 pallet",
        "description": "Overstock lot. Consumer electronics. Some units missing accessories.",
        "total_units": 85,
        "total_skus": 28,
        "total_weight_lb": 920,
        "total_cube_cuft": 48,
        "pallet_count": 1,
        "packing_type": "pallet",
        "estimated_retail_value_cents": 820000,
        "total_cost_cents": 120000,
        "condition_distribution": {"NEW": 0.40, "LIKE_NEW": 0.35, "GOOD": 0.25},
        "condition_primary": "LIKE_NEW",
        "category_primary": "electronics",
        "top_brands": ["Sony", "JBL", "Anker"],
        "ship_from_zip": "75201",
        "ship_from_state": "TX",
        "ship_from_city": "Dallas",
    })
    lot2_id = lot2["lot_id"]
    lot2 = lots.activate_lot(lot2_id, seller_id, {
        "mode": "MAKE_OFFER",
        "ask_price_cents": 180000,
        "floor_price_cents": 140000,
    })
    print(f"   → Lot ID: {lot2_id} (ACTIVE, ask: $1,800)")

    print("\n21. Buyer places offer at ask price...")
    offer2_result = offers.create_offer(buyer_id, {
        "lot_id": lot2_id,
        "offer_type": "ACCEPT_ASK",
        "offered_price_cents": 180000,
    })
    order2 = offer2_result["order"]
    order2_id = order2["order_id"]
    print(f"   → Order ID: {order2_id} (AWAITING_PAYMENT)")

    print("\n22. Buyer funds escrow...")
    esc2 = escrow_svc.get_escrow_by_order(order2_id)
    escrow_svc.fund_escrow(order2_id, buyer_id, {"method": "ach", "reference": "ach_transfer_002"})
    print(f"   → Escrow {esc2['escrow_id']} → FUNDED")

    # Generate invoices
    with db_conn() as conn:
        order2_row = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (order2_id,)).fetchone())
    invoice_svc.generate_invoices(order2_row)

    print("\n23. Shipping + delivery...")
    quote2 = freight_svc.get_freight_quote(lot2_id, "75201", buyer_id)
    ship2 = freight_svc.book_shipment(order2_id, quote2["quote_id"], 0)
    ship2_id = ship2["shipment_id"]
    freight_svc.add_tracking_event(ship2_id, "PICKED_UP", "Picked up", "Dallas", "TX", "75201")
    freight_svc.update_order_shipped(order2_id)
    freight_svc.add_tracking_event(ship2_id, "IN_TRANSIT", "In transit", "Dallas", "TX", "75201")
    freight_svc.add_tracking_event(ship2_id, "DELIVERED", "Delivered", "Dallas", "TX", "75201")
    print(f"   → Shipment {ship2_id} → DELIVERED")
    print(f"   → Order → INSPECTION (48h window)")

    # ── Dispute Flow ──

    print("\n24. Buyer files dispute: CONDITION_MISMATCH...")
    dispute = dispute_svc.create_dispute(buyer_id, {
        "order_id": order2_id,
        "type": "CONDITION_MISMATCH",
        "description": "15 units listed as NEW are clearly used/opened. Missing accessories on 8 units.",
        "affected_units": 23,
        "total_units": 85,
        "claimed_amount_cents": 50000,
        "evidence": [
            {"type": "photo", "url": "s3://evidence/photo_001.jpg", "description": "Opened packaging"},
            {"type": "photo", "url": "s3://evidence/photo_002.jpg", "description": "Missing cables"},
        ],
    })
    dispute_id = dispute["dispute_id"]
    print(f"   → Dispute ID: {dispute_id}")
    print(f"   → Status: {dispute['status']}")
    print(f"   → Claimed: ${dispute['claimed_amount_cents']/100:,.2f}")
    print(f"   → Seller response deadline: {dispute['seller_response_deadline']}")

    # Check escrow is held
    esc2_held = escrow_svc.get_escrow(esc2["escrow_id"])
    print(f"   → Escrow status: {esc2_held['status']} (held for dispute)")

    # Check order is DISPUTED
    with db_conn() as conn:
        disp_order = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (order2_id,)).fetchone())
    print(f"   → Order status: {disp_order['status']}")

    print("\n25. Seller responds to dispute...")
    dispute = dispute_svc.respond_to_dispute(dispute_id, seller_id, {
        "message": "We acknowledge some units may have been miscategorized. Willing to offer partial refund.",
        "evidence": [
            {"type": "document", "url": "s3://evidence/qa_report.pdf", "description": "QA inspection report"},
        ],
        "proposed_resolution": "PARTIAL_REFUND",
        "proposed_refund_cents": 35000,
    })
    print(f"   → Dispute status: {dispute['status']}")
    print(f"   → Seller proposed: PARTIAL_REFUND of ${35000/100:,.2f}")

    print("\n26. Buyer adds additional evidence...")
    dispute = dispute_svc.add_evidence(dispute_id, buyer_id, "buyer", {
        "type": "video",
        "url": "s3://evidence/unboxing_video.mp4",
        "description": "Unboxing video showing condition of received units",
    })
    evidence_count = len(dispute.get("buyer_evidence", []))
    print(f"   → Total evidence items: {evidence_count}")

    print("\n27. Ops resolves dispute: PARTIAL_REFUND...")
    resolution = dispute_svc.resolve_dispute(dispute_id, "ops_admin", {
        "resolution_type": "PARTIAL_REFUND",
        "refund_amount_cents": 40000,
        "reasoning": "Evidence confirms 15 units mislabeled as NEW. Awarding partial refund of $400 (proportional to affected units).",
    })
    resolved_dispute = resolution["dispute"]
    res = resolution["resolution"]
    print(f"   → Dispute status: {resolved_dispute['status']}")
    print(f"   → Resolution: {res['resolution_type']}")
    print(f"   → Refund: ${res['refund_amount_cents']/100:,.2f} to buyer")
    print(f"   → Resolution ID: {res['resolution_id']}")

    # Check final escrow status
    esc2_final = escrow_svc.get_escrow(esc2["escrow_id"])
    print(f"   → Escrow status: {esc2_final['status']}")

    # Check reputation impacts
    with db_conn() as conn:
        seller_score_final = conn.execute("SELECT quality_score, dispute_rate_pct FROM sellers WHERE seller_id = ?",
                                           (seller_id,)).fetchone()
        buyer_score_final = conn.execute("SELECT trust_score FROM buyers WHERE buyer_id = ?",
                                          (buyer_id,)).fetchone()
        rep_count = conn.execute("SELECT COUNT(*) as c FROM reputation_events").fetchone()["c"]

    print(f"\n28. Final reputation scores:")
    print(f"   → Seller quality_score: {seller_score_final['quality_score']} (dispute impact: -1 filed, -2 resolved against)")
    print(f"   → Seller dispute_rate: {seller_score_final['dispute_rate_pct']}%")
    print(f"   → Buyer trust_score: {buyer_score_final['trust_score']} (+1 resolved in favor)")
    print(f"   → Total reputation events: {rep_count}")

    print("\n" + "=" * 60)
    print("SEED COMPLETE — Two full transactions:")
    print(f"")
    print(f"  TRANSACTION 1 (happy path):")
    print(f"    Lot:       {lot_id} → SOLD")
    print(f"    Order:     {order_id} → COMPLETED")
    print(f"    Escrow:    {esc['escrow_id']} → RELEASED")
    print(f"    Payout:    {payout['payout_id']} → ${payout['amount_cents']/100:,.2f}")
    print(f"")
    print(f"  TRANSACTION 2 (dispute path):")
    print(f"    Lot:       {lot2_id}")
    print(f"    Order:     {order2_id} → DISPUTED")
    print(f"    Dispute:   {dispute_id} → RESOLVED (PARTIAL_REFUND $400)")
    print(f"    Escrow:    {esc2['escrow_id']} → {esc2_final['status']}")
    print(f"")
    print(f"  Seller: {seller_id} (score: {seller_score_final['quality_score']})")
    print(f"  Buyer:  {buyer_id} (score: {buyer_score_final['trust_score']})")
    print("=" * 60)

    # Print dashboard stats
    with db_conn() as conn:
        print("\nDatabase stats:")
        for table in ["sellers", "buyers", "buyer_intent_profiles", "canonical_products",
                       "lots", "lot_line_items", "normalized_line_items", "offers",
                       "counter_offers", "orders", "escrow_transactions", "invoices",
                       "shipments", "tracking_events", "payouts", "reputation_events",
                       "disputes", "resolutions", "audit_log"]:
            count = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
            print(f"  {table}: {count} rows")


if __name__ == "__main__":
    seed()
