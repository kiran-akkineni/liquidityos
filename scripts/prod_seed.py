"""
Production seed — idempotent setup for first deploy.
Creates schema + demo data only if tables are empty.
NEVER exits with error — gunicorn must start regardless.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("prod_seed.py: starting", flush=True)
print(f"prod_seed.py: Python {sys.version}", flush=True)
print(f"prod_seed.py: cwd={os.getcwd()}", flush=True)
print(f"prod_seed.py: DATABASE_URL={'set (' + os.environ['DATABASE_URL'].split('@')[-1] + ')' if os.environ.get('DATABASE_URL') else 'NOT SET (using sqlite)'}", flush=True)
print(f"prod_seed.py: PORT={os.environ.get('PORT', 'not set')}", flush=True)

# ── Step 0: Raw connection test before importing any app code ──
database_url = os.environ.get("DATABASE_URL")
if database_url:
    print("prod_seed.py: testing raw psycopg2 connection...", flush=True)
    try:
        import psycopg2
        url = database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()
        print(f"prod_seed.py: Postgres connection OK (SELECT 1 = {result[0]})", flush=True)
        cur.close()
        conn.close()
    except ImportError:
        print("prod_seed.py: ERROR — psycopg2 not installed!", flush=True)
        traceback.print_exc()
    except Exception as e:
        print(f"prod_seed.py: ERROR — Postgres connection failed: {e}", flush=True)
        traceback.print_exc()
else:
    print("prod_seed.py: no DATABASE_URL, will use SQLite", flush=True)


def prod_seed():
    # ── Step 1: Import app modules ──
    try:
        from app.db import init_db, get_db, is_postgres
        print(f"prod_seed.py: app modules imported, using {'postgres' if is_postgres() else 'sqlite'}", flush=True)
    except Exception as e:
        print(f"prod_seed.py: FAILED to import app modules: {e}", flush=True)
        traceback.print_exc()
        return

    # ── Step 2: Initialize schema ──
    try:
        init_db()
        print("prod_seed.py: schema initialized OK", flush=True)
    except Exception as e:
        print(f"prod_seed.py: schema init failed: {e}", flush=True)
        traceback.print_exc()
        return

    # ── Step 3: Check if already seeded ──
    try:
        with get_db() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM sellers").fetchone()
            count = row["c"] if isinstance(row, dict) else row[0]
        if count > 0:
            print(f"prod_seed.py: already seeded ({count} sellers) — skipping", flush=True)
            return
    except Exception as e:
        print(f"prod_seed.py: seed check failed: {e}", flush=True)
        traceback.print_exc()
        return

    # ── Step 4: Seed demo data ──
    print("prod_seed.py: first deploy — seeding demo data...", flush=True)
    try:
        from app.utils.helpers import make_id, now_iso, json_dumps
        from app.services import sellers, buyers, lots

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
        print(f"prod_seed.py: seller created: {seller_id}", flush=True)

        buyer = buyers.register_buyer({
            "buyer_type": "ecom_reseller",
            "business_name": "DemoBuyer LLC",
            "primary_contact_name": "Demo Buyer",
            "primary_contact_email": "buyer@liquidityos.com",
            "sales_channels": ["amazon_fba", "ebay"],
        })
        buyer_id = buyer["buyer_id"]
        buyers.verify_buyer(buyer_id, "APPROVED", "ops_admin")
        print(f"prod_seed.py: buyer created: {buyer_id}", flush=True)

        buyers.create_intent_profile(buyer_id, {
            "profile_name": "Default",
            "category_filters": {"include": ["electronics", "home_kitchen"]},
            "condition_min": "GOOD",
            "economics": {"margin_target_pct": 35, "max_lot_cost_cents": 500000},
            "logistics": {"destination_zip": "75201"},
        })

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
        print(f"prod_seed.py: {len(demo_products)} products created", flush=True)

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
        print(f"prod_seed.py: lot created and activated: {lot['lot_id']}", flush=True)
        print(f"prod_seed.py: seed complete!", flush=True)

    except Exception as e:
        print(f"prod_seed.py: seed data failed (non-fatal): {e}", flush=True)
        traceback.print_exc()


if __name__ == "__main__":
    prod_seed()
    print("prod_seed.py: exiting", flush=True)
