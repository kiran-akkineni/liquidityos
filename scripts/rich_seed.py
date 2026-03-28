"""
Rich production seed — populates the marketplace with realistic demo data
that makes it look like an active, living marketplace.

Usage:
  python3 scripts/rich_seed.py                 # dry-run against local SQLite
  python3 scripts/rich_seed.py --production    # requires DATABASE_URL
"""

import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRODUCTION = "--production" in sys.argv

if PRODUCTION and not os.environ.get("DATABASE_URL"):
    print("ERROR: --production requires DATABASE_URL to be set", flush=True)
    sys.exit(1)

if not PRODUCTION:
    os.environ["LIQUIDITYOS_DB_PATH"] = "liquidityos_rich_demo.db"
    print("DRY RUN: using local SQLite (liquidityos_rich_demo.db)", flush=True)
else:
    print(f"PRODUCTION: targeting {os.environ['DATABASE_URL'].split('@')[-1]}", flush=True)

from app.db import init_db, get_db, dict_from_row, is_postgres
from app.utils.helpers import make_id, now_iso, json_dumps, PLATFORM_FEE_PCT
from app.services import sellers as seller_svc, buyers as buyer_svc, lots as lot_svc
from app.services import offers as offer_svc, escrow as escrow_svc, invoices as invoice_svc
from app.services import freight as freight_svc, fulfillment as fulfillment_svc
from app.services import disputes as dispute_svc
from app.services.audit import log_event
from datetime import datetime, timezone, timedelta


def rich_seed():
    print("Initializing schema...", flush=True)
    init_db()

    # Idempotency check
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM sellers").fetchone()
        count = row["c"] if isinstance(row, dict) else row[0]
    if count >= 5:
        print(f"Already have {count} sellers — rich seed already ran. Skipping.", flush=True)
        return

    # Clean slate if partial data exists
    if count > 0:
        print(f"Found {count} sellers (partial data) — adding rich data on top.", flush=True)

    print("Seeding rich demo data...", flush=True)

    # ══════════════════════════════════════════════════════════
    # SELLERS (5)
    # ══════════════════════════════════════════════════════════
    print("\n1. Creating 5 sellers...", flush=True)
    seller_defs = [
        {"business_name": "PalletPros LLC", "dba_name": "PalletPros", "seller_type": "liquidator",
         "primary_contact_name": "Mike Rodriguez", "primary_contact_email": "mike@palletpros.com",
         "warehouse_locations": [{"location_id": "wh_pp", "label": "Main", "address": {"city": "Dallas", "state": "TX", "zip": "75201"}}],
         "quality_score": 87, "total_transactions": 23, "total_gmv_cents": 4200000},
        {"business_name": "ReturnFlow Inc", "dba_name": "ReturnFlow", "seller_type": "3pl",
         "primary_contact_name": "Lisa Park", "primary_contact_email": "lisa@returnflow.com",
         "warehouse_locations": [{"location_id": "wh_rf", "label": "Fulfillment Center", "address": {"city": "Atlanta", "state": "GA", "zip": "30301"}}],
         "quality_score": 92, "total_transactions": 45, "total_gmv_cents": 8900000},
        {"business_name": "BrandDirect Outlet", "dba_name": "BrandDirect", "seller_type": "brand",
         "primary_contact_name": "James Chen", "primary_contact_email": "james@branddirect.com",
         "warehouse_locations": [{"location_id": "wh_bd", "label": "LA Warehouse", "address": {"city": "Los Angeles", "state": "CA", "zip": "90001"}}],
         "quality_score": 78, "total_transactions": 12, "total_gmv_cents": 1800000},
        {"business_name": "MidWest Overstock", "dba_name": "MWO", "seller_type": "retailer",
         "primary_contact_name": "Sarah Johnson", "primary_contact_email": "sarah@mwoverstock.com",
         "warehouse_locations": [{"location_id": "wh_mw", "label": "Chicago DC", "address": {"city": "Chicago", "state": "IL", "zip": "60601"}}],
         "quality_score": 85, "total_transactions": 31, "total_gmv_cents": 5600000},
        {"business_name": "Coastal Returns Co", "dba_name": "CoastalReturns", "seller_type": "liquidator",
         "primary_contact_name": "David Kim", "primary_contact_email": "david@coastalreturns.com",
         "warehouse_locations": [{"location_id": "wh_cr", "label": "Newark Facility", "address": {"city": "Newark", "state": "NJ", "zip": "07101"}}],
         "quality_score": 71, "total_transactions": 8, "total_gmv_cents": 920000},
    ]
    seller_ids = []
    ts = now_iso()
    for sd in seller_defs:
        extra = {k: sd.pop(k) for k in ["quality_score", "total_transactions", "total_gmv_cents"]}
        s = seller_svc.register_seller(sd)
        sid = s["seller_id"]
        seller_svc.verify_seller(sid, "APPROVED", "ops_admin")
        with get_db() as conn:
            conn.execute(
                "UPDATE sellers SET quality_score = ?, total_transactions = ?, total_gmv_cents = ? WHERE seller_id = ?",
                (extra["quality_score"], extra["total_transactions"], extra["total_gmv_cents"], sid))
        seller_ids.append(sid)
        print(f"   {sd['business_name']}: {sid}", flush=True)

    # ══════════════════════════════════════════════════════════
    # BUYERS (10)
    # ══════════════════════════════════════════════════════════
    print("\n2. Creating 10 buyers...", flush=True)
    buyer_defs = [
        ("FlipKing Ventures", "Dallas", "TX", "75201", ["amazon_fba", "ebay"], 35, ["home_kitchen", "toys"]),
        ("MarginMasters LLC", "Atlanta", "GA", "30301", ["amazon_fba"], 30, ["electronics", "home_kitchen"]),
        ("PrimeResale Co", "Phoenix", "AZ", "85001", ["amazon_fba", "walmart"], 40, ["toys", "sporting_goods"]),
        ("BulkBuys Inc", "Chicago", "IL", "60601", ["ebay", "amazon_fbm"], 25, ["tools", "home_kitchen"]),
        ("ValueFlip LLC", "Miami", "FL", "33101", ["amazon_fba"], 45, ["electronics", "health"]),
        ("QuickTurn Trading", "Seattle", "WA", "98101", ["amazon_fba", "ebay"], 35, ["toys", "sporting_goods"]),
        ("DealHunter Wholesale", "Denver", "CO", "80201", ["walmart", "amazon_fbm"], 30, ["tools", "home_kitchen"]),
        ("ResaleRocket", "Nashville", "TN", "37201", ["amazon_fba"], 38, ["electronics", "toys"]),
        ("ProfitPath LLC", "Houston", "TX", "77001", ["ebay", "amazon_fba"], 32, ["sporting_goods", "tools"]),
        ("ClearanceKing Inc", "Philadelphia", "PA", "19101", ["bin_store", "ebay"], 28, ["home_kitchen", "health"]),
    ]
    buyer_ids = []
    for name, city, state, zip_code, channels, margin, cats in buyer_defs:
        b = buyer_svc.register_buyer({
            "buyer_type": "ecom_reseller", "business_name": name,
            "primary_contact_name": name.split()[0] + " User",
            "primary_contact_email": name.lower().replace(" ", "") + "@example.com",
            "sales_channels": channels,
        })
        bid = b["buyer_id"]
        buyer_svc.verify_buyer(bid, "APPROVED", "ops_admin")
        # Bump purchase limits for demo
        with get_db() as conn:
            conn.execute("UPDATE buyers SET purchase_limit_cents = 2000000, purchase_limit_remaining_cents = 2000000 WHERE buyer_id = ?", (bid,))
        buyer_svc.create_intent_profile(bid, {
            "profile_name": "Main", "category_filters": {"include": cats},
            "condition_min": "GOOD",
            "channel_config": {"channels": channels, "primary_margin_channel": channels[0]},
            "economics": {"margin_target_pct": margin, "max_lot_cost_cents": 1000000},
            "logistics": {"destination_zip": zip_code},
        })
        buyer_ids.append(bid)
    print(f"   Created {len(buyer_ids)} buyers with intent profiles", flush=True)

    # ══════════════════════════════════════════════════════════
    # CANONICAL PRODUCTS (100+)
    # ══════════════════════════════════════════════════════════
    print("\n3. Seeding 100+ canonical products...", flush=True)
    products = _build_product_catalog()
    with get_db() as conn:
        for p in products:
            conn.execute(
                """INSERT INTO canonical_products
                   (product_id, upc, asin, title, brand_normalized, department,
                    category_l1, category_l2, retail_price_cents, msrp_cents,
                    resale_data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (make_id("cprod_"), p.get("upc"), p.get("asin"), p["title"], p["brand"],
                 p["dept"], p["cat1"], p.get("cat2"), p["retail"], p["retail"],
                 json_dumps(p.get("resale", {})), ts, ts))
    print(f"   Seeded {len(products)} products", flush=True)

    # ══════════════════════════════════════════════════════════
    # LOTS (20)
    # ══════════════════════════════════════════════════════════
    print("\n4. Creating 20 lots...", flush=True)
    lot_defs = _build_lot_definitions(seller_ids)
    lot_ids = {"ACTIVE": [], "SOLD": [], "UNDER_CONTRACT": [], "EXPIRED": [], "WITHDRAWN": []}
    for ld in lot_defs:
        target_status = ld.pop("_target_status")
        seller_id = ld.pop("_seller_id")
        ask = ld.pop("_ask")
        floor = ld.pop("_floor")

        lot = lot_svc.create_lot(seller_id, ld)
        lid = lot["lot_id"]

        if target_status != "DRAFT":
            lot_svc.activate_lot(lid, seller_id, {"mode": "MAKE_OFFER", "ask_price_cents": ask, "floor_price_cents": floor})

        if target_status in ("EXPIRED", "WITHDRAWN"):
            with get_db() as conn:
                conn.execute("UPDATE lots SET status = ?, updated_at = ? WHERE lot_id = ?",
                             (target_status, ts, lid))

        lot_ids.setdefault(target_status, []).append((lid, seller_id, ask))

    for status, items in lot_ids.items():
        print(f"   {status}: {len(items)} lots", flush=True)

    # ══════════════════════════════════════════════════════════
    # COMPLETED ORDERS (5)
    # ══════════════════════════════════════════════════════════
    print("\n5. Creating 5 completed orders...", flush=True)
    completed_order_ids = []
    for i, (lid, sid, ask) in enumerate(lot_ids["SOLD"][:5]):
        bid = buyer_ids[i % len(buyer_ids)]
        price = int(ask * random.uniform(0.82, 0.95))

        # Place + accept offer
        offer = offer_svc.create_offer(bid, {
            "lot_id": lid, "offer_type": "MAKE_OFFER", "offered_price_cents": price,
        })
        if "error" in offer:
            print(f"   Offer error on lot {lid}: {offer['error']}", flush=True)
            continue
        result = offer_svc.accept_offer(offer["offer_id"], sid)
        if "error" in result:
            continue
        order = result["order"]
        oid = order["order_id"]

        # Fund escrow
        escrow_svc.fund_escrow(oid, bid, {"method": "card", "reference": f"tok_{make_id('')}"})
        with get_db() as conn:
            order_row = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone())
        invoice_svc.generate_invoices(order_row)

        # Ship + deliver
        quote = freight_svc.get_freight_quote(lid, "75201", bid)
        if "error" not in quote:
            ship = freight_svc.book_shipment(oid, quote["quote_id"], 0)
            if "error" not in ship:
                shid = ship["shipment_id"]
                freight_svc.add_tracking_event(shid, "PICKED_UP", "Picked up", "Dallas", "TX", "75201")
                freight_svc.update_order_shipped(oid)
                freight_svc.add_tracking_event(shid, "IN_TRANSIT", "In transit")
                freight_svc.add_tracking_event(shid, "DELIVERED", "Delivered", "Dallas", "TX", "75201")

        # Accept inspection + payout
        fulfillment_svc.accept_inspection(oid, bid)
        completed_order_ids.append(oid)
        print(f"   Order {oid}: ${price/100:,.0f} — COMPLETED", flush=True)

    # ══════════════════════════════════════════════════════════
    # IN-PROGRESS ORDERS (2)
    # ══════════════════════════════════════════════════════════
    print("\n6. Creating 2 in-progress orders...", flush=True)
    uc_lots = lot_ids.get("UNDER_CONTRACT", [])
    for i, (lid, sid, ask) in enumerate(uc_lots[:2]):
        bid = buyer_ids[(i + 5) % len(buyer_ids)]
        price = int(ask * 0.90)
        offer = offer_svc.create_offer(bid, {
            "lot_id": lid, "offer_type": "MAKE_OFFER", "offered_price_cents": price,
        })
        if "error" in offer:
            continue
        result = offer_svc.accept_offer(offer["offer_id"], sid)
        if "error" in result:
            continue
        order = result["order"]
        oid = order["order_id"]

        escrow_svc.fund_escrow(oid, bid, {"method": "ach", "reference": f"ach_{make_id('')}"})
        with get_db() as conn:
            order_row = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone())
        invoice_svc.generate_invoices(order_row)

        quote = freight_svc.get_freight_quote(lid, "75201", bid)
        if "error" not in quote:
            ship = freight_svc.book_shipment(oid, quote["quote_id"], 0)
            if "error" not in ship and i == 1:
                # Second order: SHIPPED
                freight_svc.add_tracking_event(ship["shipment_id"], "PICKED_UP", "Picked up")
                freight_svc.update_order_shipped(oid)
                freight_svc.add_tracking_event(ship["shipment_id"], "IN_TRANSIT", "In transit")

        with get_db() as conn:
            status = conn.execute("SELECT status FROM orders WHERE order_id = ?", (oid,)).fetchone()
        s = status["status"] if isinstance(status, dict) else status[0]
        print(f"   Order {oid}: ${price/100:,.0f} — {s}", flush=True)

    # ══════════════════════════════════════════════════════════
    # DISPUTE (1)
    # ══════════════════════════════════════════════════════════
    print("\n7. Creating 1 active dispute...", flush=True)
    if len(uc_lots) > 2:
        lid, sid, ask = uc_lots[2]
        bid = buyer_ids[7]
        price = int(ask * 0.88)
        offer = offer_svc.create_offer(bid, {
            "lot_id": lid, "offer_type": "MAKE_OFFER", "offered_price_cents": price,
        })
        if "error" not in offer:
            result = offer_svc.accept_offer(offer["offer_id"], sid)
            if "error" not in result:
                order = result["order"]
                oid = order["order_id"]
                escrow_svc.fund_escrow(oid, bid, {"method": "card", "reference": f"tok_{make_id('')}"})
                with get_db() as conn:
                    order_row = dict_from_row(conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone())
                invoice_svc.generate_invoices(order_row)
                quote = freight_svc.get_freight_quote(lid, "75201", bid)
                if "error" not in quote:
                    ship = freight_svc.book_shipment(oid, quote["quote_id"], 0)
                    if "error" not in ship:
                        freight_svc.add_tracking_event(ship["shipment_id"], "PICKED_UP", "Picked up")
                        freight_svc.update_order_shipped(oid)
                        freight_svc.add_tracking_event(ship["shipment_id"], "DELIVERED", "Delivered")

                dispute = dispute_svc.create_dispute(bid, {
                    "order_id": oid, "type": "CONDITION_MISMATCH",
                    "description": "12 units listed as NEW are clearly open-box with missing accessories. Packaging damaged on 5 units.",
                    "affected_units": 17, "total_units": 85, "claimed_amount_cents": 40000,
                    "evidence": [
                        {"type": "photo", "url": "s3://evidence/condition_01.jpg", "description": "Open boxes"},
                        {"type": "photo", "url": "s3://evidence/condition_02.jpg", "description": "Missing cables"},
                    ],
                })
                dispute_svc.respond_to_dispute(dispute["dispute_id"], sid, {
                    "message": "We apologize for the discrepancy. Our QA process flagged these as new-opened. Willing to negotiate a fair resolution.",
                    "proposed_resolution": "PARTIAL_REFUND", "proposed_refund_cents": 25000,
                    "evidence": [{"type": "document", "url": "s3://evidence/qa_checklist.pdf"}],
                })
                # Move to UNDER_REVIEW
                with get_db() as conn:
                    conn.execute("UPDATE disputes SET status = 'UNDER_REVIEW', updated_at = ? WHERE dispute_id = ?",
                                 (ts, dispute["dispute_id"]))
                print(f"   Dispute {dispute['dispute_id']}: $400 claimed — UNDER_REVIEW", flush=True)

    # ══════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════
    print("\n" + "=" * 60, flush=True)
    with get_db() as conn:
        for table in ["sellers", "buyers", "buyer_intent_profiles", "canonical_products",
                       "lots", "offers", "orders", "escrow_transactions", "invoices",
                       "shipments", "payouts", "disputes", "reputation_events", "audit_log"]:
            c = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
            cnt = c["c"] if isinstance(c, dict) else c[0]
            print(f"  {table}: {cnt}", flush=True)
    print("=" * 60, flush=True)
    print("Rich seed complete!", flush=True)


# ── Product catalog builder ────────────────────────────────────────────

def _build_product_catalog():
    p = []
    # Home & Kitchen (25)
    hk = [
        ("B08N5WRWNW", "012345678901", "Instant Pot Duo 7-in-1, 6 Quart", "Instant Pot", 8999),
        ("B07S85TPLG", "012345678902", "Ninja Professional Blender, 72oz", "Ninja", 6999),
        ("B09KZ26N23", "012345678903", "KitchenAid Hand Mixer, 5-Speed", "KitchenAid", 5499),
        ("B08PZHYWJS", "611247373262", "Keurig K-Mini Single Serve Coffee Maker", "Keurig", 7999),
        ("B00006JSUA", "097855157430", "Lodge Cast Iron Skillet 12-inch", "Lodge", 3999),
        ("B00FLYWNYQ", "022578104294", "Cuisinart 14-Cup Food Processor", "Cuisinart", 19999),
        ("B075X17GS2", "027045704533", "Hamilton Beach Electric Kettle 1.7L", "Hamilton Beach", 2999),
        ("B07NQDHFP9", "885911548069", "BLACK+DECKER Toaster Oven 4-Slice", "Black+Decker", 3999),
        ("B09W5X73XG", "078742080017", "OXO Good Grips 11-Piece Kitchen Set", "OXO", 4999),
        ("B07FJ7QY3A", "612520701611", "Vitamix E310 Explorian Blender", "Vitamix", 34999),
        ("B07GCDMR6K", "885587098370", "Crock-Pot 7-Quart Slow Cooker", "Crock-Pot", 3999),
        ("B08P5NBPCJ", "810010363817", "Ninja Foodi 6-in-1 Indoor Grill", "Ninja", 14999),
        ("B07R8M5K23", "044387227018", "Pyrex 8-Piece Glass Storage Set", "Pyrex", 2499),
        ("B07BFVFMS1", "070896507143", "T-fal Nonstick 12-Piece Cookware Set", "T-fal", 7999),
        ("B07P7VBF9Q", "885911818673", "George Foreman 5-Serving Grill", "George Foreman", 3499),
        ("B09J9DQBKX", "022578109787", "Cuisinart Air Fryer Toaster Oven", "Cuisinart", 22999),
        ("B0BRV7RX63", "810116830299", "Stanley Classic Vacuum Bottle 1.1qt", "Stanley", 3500),
        ("B0CFDJQ2QQ", "810116830268", "Stanley Quencher H2.0 FlowState 40oz", "Stanley", 4500),
        ("B083GBHND7", "841058102298", "Hydro Flask 32oz Wide Mouth", "Hydro Flask", 4495),
        ("B0CFSLNJQ3", "810028587878", "Owala FreeSip 24oz Water Bottle", "Owala", 2799),
        ("B07TWTX9GR", "763332036672", "YETI Rambler 26oz Bottle", "YETI", 4000),
        ("B07GS6ZP3H", "885911687125", "Brita Large Water Filter Pitcher 10-Cup", "Brita", 3299),
        ("B079YY5LTG", "044387235013", "Corelle 18-Piece Dinnerware Set", "Corelle", 5999),
        ("B0B8KJ2RYX", "810010363824", "Ninja Creami Ice Cream Maker", "Ninja", 19999),
        ("B07HHN4YJL", "022578108292", "Cuisinart Grind & Brew 12-Cup Coffeemaker", "Cuisinart", 9999),
    ]
    for asin, upc, title, brand, retail in hk:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Home & Kitchen",
                  "cat1": "Kitchen & Dining", "cat2": "Small Appliances", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.82)}}})

    # Electronics (15)
    el = [
        ("B0BDHX9JPC", "194252774052", "Apple AirPods Pro (2nd Generation)", "Apple", 24999),
        ("B09V3KXJPB", "050036380447", "JBL Flip 6 Portable Bluetooth Speaker", "JBL", 12999),
        ("B0BT9CXXXX", "194644022120", "Anker PowerCore 20000mAh Portable Charger", "Anker", 4999),
        ("B09JQM8K1N", "027242923003", "Sony WH-1000XM5 Noise Canceling Headphones", "Sony", 34999),
        ("B09HGV7TPF", "848447017041", "Beats Studio Buds True Wireless", "Beats", 14999),
        ("B084DDDNRP", "840080543932", "Ring Video Doorbell Wired", "Ring", 6499),
        ("B09B8V1LZ3", "841667143507", "Amazon Echo Dot (5th Gen)", "Amazon", 4999),
        ("B0BX8GMDJL", "097855139030", "Logitech MX Master 3S Wireless Mouse", "Logitech", 9999),
        ("B09HMZ5M2V", "097855170262", "Logitech K380 Bluetooth Keyboard", "Logitech", 3999),
        ("B0C1K5QFS4", "718037884721", "SanDisk 1TB Extreme Portable SSD", "SanDisk", 8999),
        ("B0BVMKCZYD", "195949067518", "Bose QuietComfort Ultra Earbuds", "Bose", 29999),
        ("B0BF4N2KQP", "860007780112", "Govee Smart LED Strip Lights 65.6ft", "Govee", 3999),
        ("B09GJ5P3FZ", "840006651229", "Roku Streaming Stick 4K", "Roku", 4999),
        ("B0CG5GP75Y", "817707025637", "Fire TV Stick 4K Max (2nd Gen)", "Amazon", 5999),
        ("B0CHX3QBCH", "190199882744", "Apple Watch SE (2nd Gen) 40mm GPS", "Apple", 24900),
    ]
    for asin, upc, title, brand, retail in el:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Electronics",
                  "cat1": "Electronics", "cat2": "Accessories", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.78)}}})

    # Toys & Games (20)
    toys = [
        ("B07V8BDFHQ", "072785138681", "Crayola 96 Count Crayons", "Crayola", 599),
        ("B0BKF9HJR4", "630509971671", "NERF Elite 2.0 Eaglepoint RD-8", "NERF", 3499),
        ("B09NLRPCMK", "887961962017", "Barbie Dreamhouse 2023", "Barbie", 17999),
        ("B09FM97L7B", "673419340281", "LEGO Star Wars Millennium Falcon", "LEGO", 8499),
        ("B0B6GZMB7Q", "630509985784", "Play-Doh Kitchen Creations Set", "Play-Doh", 1999),
        ("B09WJPHJ35", "887961960051", "Hot Wheels Ultimate Garage Playset", "Hot Wheels", 9999),
        ("B0BG3YC7P2", "778988364017", "Paw Patrol Mighty Movie Cruiser", "Paw Patrol", 4999),
        ("B0BQXRHC3T", "630510001231", "Monopoly Classic Board Game", "Hasbro", 1999),
        ("B0C5H89GN7", "673419378482", "LEGO Technic McLaren P1", "LEGO", 4999),
        ("B0B7QJYR3Q", "887961965131", "Barbie Pop Reveal Fruit Series", "Barbie", 1499),
        ("B09R3RRJMY", "778988373255", "Gabby's Dollhouse Playset", "Gabby's Dollhouse", 5999),
        ("B0BY89TLHD", "195166216829", "Pokemon TCG Booster Bundle", "Pokemon", 2499),
        ("B0BMR5CHYN", "630510001248", "Jenga Classic Game", "Hasbro", 1299),
        ("B0C8F7XPKJ", "887961966879", "UNO Show 'em No Mercy", "Mattel", 1299),
        ("B0B6H3YWKK", "630509985791", "Transformers Rise of the Beasts", "Transformers", 2999),
        ("B0BNM7P7C7", "778988432440", "Kinetic Sand Sandisfying Set", "Kinetic Sand", 1499),
        ("B09TZL91XP", "195166175700", "Squishmallows 16-inch Plush", "Squishmallows", 2499),
        ("B0B8RMLR2D", "673419358941", "LEGO Friends Heartlake City", "LEGO", 6999),
        ("B0BF1HLFK4", "630510000987", "Hungry Hungry Hippos", "Hasbro", 1499),
        ("B09WGZN2YT", "887961966500", "Fisher-Price Little People Farm", "Fisher-Price", 3999),
    ]
    for asin, upc, title, brand, retail in toys:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Toys",
                  "cat1": "Toys", "cat2": "Games", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.75)}}})

    # Sporting Goods (15)
    sg = [
        ("B08F4WPCZC", "889769032897", "Callaway Strata Golf Set 12-Piece", "Callaway", 29999),
        ("B09R8JGJPY", "889769085893", "TaylorMade Stealth 2 Driver", "TaylorMade", 59999),
        ("B07WD3NXKJ", "888830093252", "YETI Tundra 45 Cooler", "YETI", 32500),
        ("B0B3CXGHCN", "076501117424", "Coleman SunDome 4-Person Tent", "Coleman", 7999),
        ("B07S9X98WZ", "022099559115", "Manduka PRO Yoga Mat 71-inch", "Manduka", 12000),
        ("B08FJ7QY3T", "733739045201", "Bowflex SelectTech 552 Dumbbells", "Bowflex", 42999),
        ("B09HMBF5N7", "818137013468", "Hydrow Rower", "Hydrow", 249500),
        ("B08CXMF4DX", "810028581418", "CamelBak Chute Mag 32oz", "CamelBak", 1800),
        ("B0BV28Q3YR", "079946039031", "Spalding NBA Official Basketball", "Spalding", 2999),
        ("B0847Y2T2M", "083321200908", "Fitbit Charge 5 Fitness Tracker", "Fitbit", 14995),
        ("B08R4J3YB5", "810010363831", "NordicTrack T 6.5 Si Treadmill", "NordicTrack", 64999),
        ("B0BX9RPYJ7", "889769098602", "Titleist Pro V1 Golf Balls (12pk)", "Titleist", 5499),
        ("B07GDB5N7M", "858558006085", "NOCO Boost Plus GB40 Jump Starter", "NOCO", 9995),
        ("B0BN8ZKRK3", "194277528831", "Under Armour Charged Assert 10", "Under Armour", 7000),
        ("B0BY1L5BN7", "193394075359", "Nike Dri-FIT Running Shorts", "Nike", 3500),
    ]
    for asin, upc, title, brand, retail in sg:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Sports",
                  "cat1": "Sporting Goods", "cat2": "Fitness", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.72)}}})

    # Tools (15)
    tools = [
        ("B004GIO0F6", "885911256568", "DEWALT 20V MAX Drill/Driver Kit", "DeWalt", 9999),
        ("B07KTKJFB2", "045242530144", "Milwaukee M18 FUEL Impact Driver", "Milwaukee", 17999),
        ("B08JCDYTKP", "885911732697", "BLACK+DECKER 20V Cordless Drill", "Black+Decker", 5999),
        ("B07B9NXMG3", "028877593098", "Craftsman 256-Piece Mechanics Tool Set", "Craftsman", 19999),
        ("B08BN8QFSQ", "731919233377", "Ryobi ONE+ 18V Combo Kit (5-Tool)", "Ryobi", 19900),
        ("B07JGGNQPB", "028877599618", "Craftsman V20 Circular Saw", "Craftsman", 12999),
        ("B0012ULSRK", "028907030517", "Gorilla Glue Original 8oz", "Gorilla", 999),
        ("B000IDUKQ8", "078628079001", "Dremel 3000 Rotary Tool Kit", "Dremel", 6999),
        ("B00FHPKBC4", "076174900767", "Klein Tools 11-in-1 Screwdriver", "Klein Tools", 1799),
        ("B0B3PSRHHN", "885609027562", "Dyson V8 Origin Cordless Vacuum", "Dyson", 34999),
        ("B07QXM74K8", "811061020521", "iRobot Roomba 694 Robot Vacuum", "iRobot", 27499),
        ("B09NKSFB5X", "810019267901", "Shark Navigator Upright Vacuum", "Shark", 19999),
        ("B09VKLXVFL", "045242630547", "Milwaukee M12 Heated Jacket Kit", "Milwaukee", 19900),
        ("B08JQY9ZLH", "885911716109", "DEWALT 20V MAX Blower", "DeWalt", 12999),
        ("B07M8RKJZL", "731919233384", "Ryobi 40V Brushless Lawn Mower", "Ryobi", 29900),
    ]
    for asin, upc, title, brand, retail in tools:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Tools",
                  "cat1": "Tools", "cat2": "Power Tools", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.70)}}})

    # Health (10)
    health = [
        ("B09W5X73AA", "075020073914", "Philips Sonicare 4100 Toothbrush", "Philips", 4999),
        ("B08GS7MFHZ", "074108360243", "Braun Series 5 Electric Shaver", "Braun", 7999),
        ("B07MPRB2QD", "071249351338", "Revlon One-Step Hair Dryer", "Revlon", 3499),
        ("B09JQMKQRW", "069055883860", "Oral-B iO Series 5 Toothbrush", "Oral-B", 9999),
        ("B0BFVY2ZYJ", "071249408728", "Conair InfinitiPro Blow Dryer", "Conair", 2999),
        ("B0B6J6TJ9C", "074108396693", "Braun Silk-Expert Pro 5", "Braun", 29999),
        ("B0BXM6GVVJ", "037000795643", "Gillette Labs Exfoliating Razor", "Gillette", 2999),
        ("B089Q39QXH", "729849157804", "Furbo Dog Camera 360", "Furbo", 17999),
        ("B085VYM6WQ", "816268012422", "Baby Brezza Formula Pro Advanced", "Baby Brezza", 19999),
        ("B0C8F6YYS7", "196534735804", "Samsung Galaxy Buds FE", "Samsung", 9999),
    ]
    for asin, upc, title, brand, retail in health:
        p.append({"asin": asin, "upc": upc, "title": title, "brand": brand, "dept": "Health",
                  "cat1": "Health", "cat2": "Personal Care", "retail": retail,
                  "resale": {"amazon_fba": {"current_listing_price_cents": int(retail * 0.75)}}})

    return p


# ── Lot definitions ────────────────────────────────────────────────────

def _build_lot_definitions(seller_ids):
    s = seller_ids
    lots = [
        # 8 ACTIVE
        {"_target_status": "ACTIVE", "_seller_id": s[0], "_ask": 280000, "_floor": 220000,
         "title": "Mixed Home & Kitchen — 127 units, 2 pallets", "total_units": 127, "total_skus": 42,
         "pallet_count": 2, "total_weight_lb": 1840, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 1240000, "total_cost_cents": 180000,
         "condition_distribution": {"NEW": 0.65, "LIKE_NEW": 0.30, "GOOD": 0.05}, "condition_primary": "NEW",
         "category_primary": "home_kitchen", "top_brands": ["Instant Pot", "Ninja", "KitchenAid", "OXO"],
         "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas"},
        {"_target_status": "ACTIVE", "_seller_id": s[1], "_ask": 450000, "_floor": 350000,
         "title": "Premium Electronics Accessories — 200 units, 3 pallets", "total_units": 200, "total_skus": 35,
         "pallet_count": 3, "total_weight_lb": 980, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 2800000, "total_cost_cents": 280000,
         "condition_distribution": {"NEW": 0.80, "LIKE_NEW": 0.20}, "condition_primary": "NEW",
         "category_primary": "electronics", "top_brands": ["Apple", "JBL", "Anker", "Beats"],
         "ship_from_zip": "30301", "ship_from_state": "GA", "ship_from_city": "Atlanta"},
        {"_target_status": "ACTIVE", "_seller_id": s[2], "_ask": 150000, "_floor": 110000,
         "title": "Toy Closeout — LEGO, Nerf, Barbie — 300 units", "total_units": 300, "total_skus": 45,
         "pallet_count": 4, "total_weight_lb": 2200, "total_cube_cuft": 192,
         "estimated_retail_value_cents": 890000, "total_cost_cents": 95000,
         "condition_distribution": {"NEW": 0.90, "LIKE_NEW": 0.10}, "condition_primary": "NEW",
         "category_primary": "toys", "top_brands": ["LEGO", "NERF", "Barbie", "Hasbro"],
         "ship_from_zip": "90001", "ship_from_state": "CA", "ship_from_city": "Los Angeles"},
        {"_target_status": "ACTIVE", "_seller_id": s[3], "_ask": 520000, "_floor": 400000,
         "title": "DeWalt + Milwaukee Tool Overstock — 85 units", "total_units": 85, "total_skus": 20,
         "pallet_count": 2, "total_weight_lb": 1600, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 1850000, "total_cost_cents": 320000,
         "condition_distribution": {"NEW": 0.70, "LIKE_NEW": 0.25, "GOOD": 0.05}, "condition_primary": "NEW",
         "category_primary": "tools", "top_brands": ["DeWalt", "Milwaukee", "Ryobi"],
         "ship_from_zip": "60601", "ship_from_state": "IL", "ship_from_city": "Chicago"},
        {"_target_status": "ACTIVE", "_seller_id": s[4], "_ask": 180000, "_floor": 140000,
         "title": "Health & Personal Care Returns — 150 units", "total_units": 150, "total_skus": 30,
         "pallet_count": 2, "total_weight_lb": 600, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 750000, "total_cost_cents": 110000,
         "condition_distribution": {"NEW": 0.50, "LIKE_NEW": 0.30, "GOOD": 0.20}, "condition_primary": "NEW",
         "category_primary": "health", "top_brands": ["Philips", "Braun", "Oral-B", "Revlon"],
         "ship_from_zip": "07101", "ship_from_state": "NJ", "ship_from_city": "Newark"},
        {"_target_status": "ACTIVE", "_seller_id": s[0], "_ask": 350000, "_floor": 270000,
         "title": "Sporting Goods Liquidation — Golf + Fitness — 95 units", "total_units": 95, "total_skus": 22,
         "pallet_count": 3, "total_weight_lb": 2800, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 1600000, "total_cost_cents": 220000,
         "condition_distribution": {"NEW": 0.55, "LIKE_NEW": 0.35, "GOOD": 0.10}, "condition_primary": "NEW",
         "category_primary": "sporting_goods", "top_brands": ["Callaway", "YETI", "Bowflex", "Coleman"],
         "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas"},
        {"_target_status": "ACTIVE", "_seller_id": s[1], "_ask": 800000, "_floor": 650000,
         "title": "Apple + Sony Premium Electronics — 50 units, high-value", "total_units": 50, "total_skus": 8,
         "pallet_count": 1, "total_weight_lb": 320, "total_cube_cuft": 48,
         "estimated_retail_value_cents": 4200000, "total_cost_cents": 520000,
         "condition_distribution": {"NEW": 0.60, "LIKE_NEW": 0.40}, "condition_primary": "NEW",
         "category_primary": "electronics", "top_brands": ["Apple", "Sony", "Bose"],
         "ship_from_zip": "30301", "ship_from_state": "GA", "ship_from_city": "Atlanta"},
        {"_target_status": "ACTIVE", "_seller_id": s[3], "_ask": 220000, "_floor": 170000,
         "title": "Kitchen Small Appliances — Keurig, Ninja, Cuisinart — 180 units", "total_units": 180, "total_skus": 28,
         "pallet_count": 3, "total_weight_lb": 1500, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 1100000, "total_cost_cents": 140000,
         "condition_distribution": {"NEW": 0.40, "LIKE_NEW": 0.40, "GOOD": 0.20}, "condition_primary": "LIKE_NEW",
         "category_primary": "home_kitchen", "top_brands": ["Keurig", "Ninja", "Cuisinart", "Hamilton Beach"],
         "ship_from_zip": "60601", "ship_from_state": "IL", "ship_from_city": "Chicago"},
        # 5 SOLD
        {"_target_status": "SOLD", "_seller_id": s[0], "_ask": 260000, "_floor": 200000,
         "title": "Home & Kitchen Overstock — 110 units", "total_units": 110, "total_skus": 35,
         "pallet_count": 2, "total_weight_lb": 1400, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 980000, "total_cost_cents": 160000,
         "condition_distribution": {"NEW": 0.70, "LIKE_NEW": 0.30}, "condition_primary": "NEW",
         "category_primary": "home_kitchen", "top_brands": ["Instant Pot", "Lodge", "Brita"],
         "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas"},
        {"_target_status": "SOLD", "_seller_id": s[1], "_ask": 380000, "_floor": 300000,
         "title": "Electronics Bundle — Headphones + Speakers — 160 units", "total_units": 160, "total_skus": 25,
         "pallet_count": 2, "total_weight_lb": 640, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 2100000, "total_cost_cents": 240000,
         "condition_distribution": {"NEW": 0.75, "LIKE_NEW": 0.25}, "condition_primary": "NEW",
         "category_primary": "electronics", "top_brands": ["JBL", "Beats", "Sony", "Anker"],
         "ship_from_zip": "30301", "ship_from_state": "GA", "ship_from_city": "Atlanta"},
        {"_target_status": "SOLD", "_seller_id": s[2], "_ask": 190000, "_floor": 140000,
         "title": "Toy Clearance — Board Games + Action Figures — 250 units", "total_units": 250, "total_skus": 40,
         "pallet_count": 3, "total_weight_lb": 1800, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 720000, "total_cost_cents": 100000,
         "condition_distribution": {"NEW": 0.85, "LIKE_NEW": 0.15}, "condition_primary": "NEW",
         "category_primary": "toys", "top_brands": ["Hasbro", "Mattel", "LEGO"],
         "ship_from_zip": "90001", "ship_from_state": "CA", "ship_from_city": "Los Angeles"},
        {"_target_status": "SOLD", "_seller_id": s[3], "_ask": 600000, "_floor": 480000,
         "title": "Power Tools Pallet — DeWalt + Craftsman — 60 units", "total_units": 60, "total_skus": 15,
         "pallet_count": 2, "total_weight_lb": 1900, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 2400000, "total_cost_cents": 380000,
         "condition_distribution": {"NEW": 0.80, "LIKE_NEW": 0.20}, "condition_primary": "NEW",
         "category_primary": "tools", "top_brands": ["DeWalt", "Craftsman", "Ryobi"],
         "ship_from_zip": "60601", "ship_from_state": "IL", "ship_from_city": "Chicago"},
        {"_target_status": "SOLD", "_seller_id": s[4], "_ask": 240000, "_floor": 180000,
         "title": "Mixed Returns — Electronics + Home — 175 units", "total_units": 175, "total_skus": 38,
         "pallet_count": 3, "total_weight_lb": 1300, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 1050000, "total_cost_cents": 150000,
         "condition_distribution": {"NEW": 0.45, "LIKE_NEW": 0.35, "GOOD": 0.20}, "condition_primary": "LIKE_NEW",
         "category_primary": "electronics", "top_brands": ["Amazon", "Roku", "Govee", "Ring"],
         "ship_from_zip": "07101", "ship_from_state": "NJ", "ship_from_city": "Newark"},
        # 3 UNDER_CONTRACT
        {"_target_status": "UNDER_CONTRACT", "_seller_id": s[0], "_ask": 310000, "_floor": 240000,
         "title": "Drinkware Mega Lot — Stanley, YETI, Hydro Flask — 220 units", "total_units": 220, "total_skus": 15,
         "pallet_count": 3, "total_weight_lb": 1100, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 880000, "total_cost_cents": 190000,
         "condition_distribution": {"NEW": 0.90, "LIKE_NEW": 0.10}, "condition_primary": "NEW",
         "category_primary": "home_kitchen", "top_brands": ["Stanley", "YETI", "Hydro Flask", "Owala"],
         "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas"},
        {"_target_status": "UNDER_CONTRACT", "_seller_id": s[1], "_ask": 420000, "_floor": 330000,
         "title": "Smart Home Bundle — Ring, Echo, Roku — 90 units", "total_units": 90, "total_skus": 12,
         "pallet_count": 1, "total_weight_lb": 450, "total_cube_cuft": 48,
         "estimated_retail_value_cents": 1500000, "total_cost_cents": 260000,
         "condition_distribution": {"NEW": 0.65, "LIKE_NEW": 0.35}, "condition_primary": "NEW",
         "category_primary": "electronics", "top_brands": ["Ring", "Amazon", "Roku", "Govee"],
         "ship_from_zip": "30301", "ship_from_state": "GA", "ship_from_city": "Atlanta"},
        {"_target_status": "UNDER_CONTRACT", "_seller_id": s[3], "_ask": 280000, "_floor": 210000,
         "title": "Vacuum + Cleaning Lot — Dyson, Shark, iRobot — 45 units", "total_units": 45, "total_skus": 10,
         "pallet_count": 2, "total_weight_lb": 900, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 1200000, "total_cost_cents": 180000,
         "condition_distribution": {"LIKE_NEW": 0.60, "GOOD": 0.30, "FAIR": 0.10}, "condition_primary": "LIKE_NEW",
         "category_primary": "home_kitchen", "top_brands": ["Dyson", "Shark", "iRobot"],
         "ship_from_zip": "60601", "ship_from_state": "IL", "ship_from_city": "Chicago"},
        # 2 EXPIRED
        {"_target_status": "EXPIRED", "_seller_id": s[4], "_ask": 160000, "_floor": 120000,
         "title": "Seasonal Toys — Holiday Clearance — 200 units", "total_units": 200, "total_skus": 50,
         "pallet_count": 3, "total_weight_lb": 1600, "total_cube_cuft": 144,
         "estimated_retail_value_cents": 600000, "total_cost_cents": 80000,
         "condition_distribution": {"NEW": 0.95, "LIKE_NEW": 0.05}, "condition_primary": "NEW",
         "category_primary": "toys", "top_brands": ["Fisher-Price", "Squishmallows", "Play-Doh"],
         "ship_from_zip": "07101", "ship_from_state": "NJ", "ship_from_city": "Newark"},
        {"_target_status": "EXPIRED", "_seller_id": s[2], "_ask": 750000, "_floor": 600000,
         "title": "Premium Golf Equipment — Callaway + TaylorMade — 30 units", "total_units": 30, "total_skus": 8,
         "pallet_count": 1, "total_weight_lb": 500, "total_cube_cuft": 48,
         "estimated_retail_value_cents": 3500000, "total_cost_cents": 500000,
         "condition_distribution": {"NEW": 0.70, "LIKE_NEW": 0.30}, "condition_primary": "NEW",
         "category_primary": "sporting_goods", "top_brands": ["Callaway", "TaylorMade", "Titleist"],
         "ship_from_zip": "90001", "ship_from_state": "CA", "ship_from_city": "Los Angeles"},
        # 2 WITHDRAWN
        {"_target_status": "WITHDRAWN", "_seller_id": s[0], "_ask": 200000, "_floor": 150000,
         "title": "Mixed Salvage — Customer Returns — 100 units", "total_units": 100, "total_skus": 60,
         "pallet_count": 2, "total_weight_lb": 800, "total_cube_cuft": 96,
         "estimated_retail_value_cents": 400000, "total_cost_cents": 50000,
         "condition_distribution": {"GOOD": 0.40, "FAIR": 0.40, "SALVAGE": 0.20}, "condition_primary": "FAIR",
         "category_primary": "home_kitchen", "top_brands": ["Various"],
         "ship_from_zip": "75201", "ship_from_state": "TX", "ship_from_city": "Dallas"},
        {"_target_status": "WITHDRAWN", "_seller_id": s[4], "_ask": 340000, "_floor": 260000,
         "title": "Electronics Scratch & Dent — 70 units", "total_units": 70, "total_skus": 18,
         "pallet_count": 1, "total_weight_lb": 500, "total_cube_cuft": 48,
         "estimated_retail_value_cents": 1400000, "total_cost_cents": 200000,
         "condition_distribution": {"GOOD": 0.50, "FAIR": 0.40, "SALVAGE": 0.10}, "condition_primary": "GOOD",
         "category_primary": "electronics", "top_brands": ["Logitech", "SanDisk", "Anker"],
         "ship_from_zip": "07101", "ship_from_state": "NJ", "ship_from_city": "Newark"},
    ]
    return lots


if __name__ == "__main__":
    rich_seed()
