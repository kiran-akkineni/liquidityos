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

    print("\n" + "=" * 60)
    print("SEED COMPLETE — Full negotiation flow executed:")
    print(f"  Seller: {seller_id}")
    print(f"  Buyer:  {buyer_id}")
    print(f"  Lot:    {lot_id}")
    print(f"  Offer:  {offer_id} → countered → accepted")
    print(f"  Order:  {order['order_id']}")
    print("=" * 60)

    # Print dashboard stats
    from app.db import get_db
    with db_conn() as conn:
        print("\nDatabase stats:")
        for table in ["sellers", "buyers", "buyer_intent_profiles", "canonical_products",
                       "lots", "lot_line_items", "normalized_line_items", "offers",
                       "counter_offers", "orders", "audit_log"]:
            count = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()["c"]
            print(f"  {table}: {count} rows")


if __name__ == "__main__":
    seed()
