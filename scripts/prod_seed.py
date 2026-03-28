"""
Production seed — idempotent setup for first deploy.
Creates schema + demo data only if tables are empty.
Run before gunicorn starts (via Dockerfile CMD).
"""

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("liquidityos.seed")


def prod_seed():
    logger.info("Running production seed...")

    # Initialize schema first
    from app.db import init_db, get_db, is_postgres
    try:
        init_db()
    except Exception as e:
        logger.error("Schema init failed: %s", e, exc_info=True)
        sys.exit(1)

    # Check if data already exists
    try:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM sellers").fetchone()
            count = row["c"] if isinstance(row, dict) else row[0]
        if count > 0:
            logger.info("Database already seeded (%d sellers) — skipping.", count)
            return
    except Exception as e:
        logger.error("Failed to check seed status: %s", e, exc_info=True)
        sys.exit(1)

    logger.info("First deploy — seeding demo data...")

    from app.utils.helpers import make_id, now_iso, json_dumps
    from app.services import sellers, buyers, lots

    try:
        # Demo seller
        seller = sellers.register_seller({
            "seller_type": "liquidator",
            "business_name": "DemoSeller Inc",
            "dba_name": "DemoSeller",
            "primary_contact_name": "Demo User",
            "primary_contact_email": "demo@liquidityos.com",
            "warehouse_locations": [{"location_id": "wh_01", "label": "Main",
                "address": {"city": "Dallas", "state": "TX", "zip": "75201"}}],
        })
        seller_id = seller["seller_id"]
        sellers.verify_seller(seller_id, "APPROVED", "ops_admin")

        # Demo buyer
        buyer = buyers.register_buyer({
            "buyer_type": "ecom_reseller",
            "business_name": "DemoBuyer LLC",
            "primary_contact_name": "Demo Buyer",
            "primary_contact_email": "buyer@liquidityos.com",
            "sales_channels": ["amazon_fba", "ebay"],
        })
        buyer_id = buyer["buyer_id"]
        buyers.verify_buyer(buyer_id, "APPROVED", "ops_admin")

        # Buyer intent profile
        buyers.create_intent_profile(buyer_id, {
            "profile_name": "Default",
            "category_filters": {"include": ["electronics", "home_kitchen"]},
            "condition_min": "GOOD",
            "economics": {"margin_target_pct": 35, "max_lot_cost_cents": 500000},
            "logistics": {"destination_zip": "75201"},
        })

        # Canonical products
        ts = now_iso()
        demo_products = [
            {"upc": "012345678901", "asin": "B08N5WRWNW", "title": "Instant Pot Duo 7-in-1, 6 Quart", "brand_normalized": "Instant Pot", "department": "Home & Kitchen", "category_l1": "Kitchen & Dining", "retail_price_cents": 8999, "msrp_cents": 8999, "resale_data": {"amazon_fba": {"current_listing_price_cents": 7499}}},
            {"upc": "194252774052", "asin": "B0BDHX9JPC", "title": "Apple AirPods Pro (2nd Generation)", "brand_normalized": "Apple", "department": "Electronics", "category_l1": "Electronics", "retail_price_cents": 24999, "msrp_cents": 24999, "resale_data": {"amazon_fba": {"current_listing_price_cents": 18999}}},
            {"upc": "050036380447", "asin": "B09V3KXJPB", "title": "JBL Flip 6 Portable Bluetooth Speaker", "brand_normalized": "JBL", "department": "Electronics", "category_l1": "Electronics", "retail_price_cents": 12999, "msrp_cents": 12999, "resale_data": {}},
            {"upc": "027242923003", "asin": "B09JQM8K1N", "title": "Sony WH-1000XM5 Headphones", "brand_normalized": "Sony", "department": "Electronics", "category_l1": "Electronics", "retail_price_cents": 34999, "msrp_cents": 39999, "resale_data": {}},
            {"upc": "810116830268", "asin": "B0CFDJQ2QQ", "title": "Stanley Quencher H2.0 FlowState Tumbler 40oz", "brand_normalized": "Stanley", "department": "Outdoors", "category_l1": "Outdoors", "retail_price_cents": 4500, "msrp_cents": 4500, "resale_data": {}},
        ]
        with get_db() as conn:
            for p in demo_products:
                conn.execute(
                    """INSERT INTO canonical_products
                       (product_id, upc, asin, title, brand_normalized, department,
                        category_l1, retail_price_cents, msrp_cents, resale_data,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (make_id("cprod_"), p["upc"], p["asin"], p["title"], p["brand_normalized"],
                     p["department"], p["category_l1"], p["retail_price_cents"],
                     p["msrp_cents"], json_dumps(p.get("resale_data", {})), ts, ts),
                )

        # Demo lot
        lot = lots.create_lot(seller_id, {
            "title": "Mixed Electronics — 100 units, 2 pallets",
            "description": "Demo lot with consumer electronics.",
            "total_units": 100, "total_skus": 25, "pallet_count": 2,
            "total_weight_lb": 1200, "total_cube_cuft": 96,
            "estimated_retail_value_cents": 950000, "total_cost_cents": 150000,
            "condition_distribution": {"NEW": 0.60, "LIKE_NEW": 0.30, "GOOD": 0.10},
            "condition_primary": "NEW",
            "category_primary": "electronics",
            "top_brands": ["Apple", "Sony", "JBL", "Anker"],
            "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas",
        })
        lots.activate_lot(lot["lot_id"], seller_id, {
            "mode": "MAKE_OFFER",
            "ask_price_cents": 280000,
            "floor_price_cents": 220000,
        })

        logger.info("Demo data seeded: seller=%s, buyer=%s, lot=%s", seller_id, buyer_id, lot["lot_id"])

    except Exception as e:
        logger.error("Seed failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    prod_seed()
