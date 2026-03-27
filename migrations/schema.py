"""
LiquidityOS Database Schema
All 26 tables from the data model specification.
SQLite for development; annotated with Postgres migration notes.

Convention:
- All monetary values in integer cents (USD)
- All timestamps UTC ISO 8601
- UUIDs as TEXT primary keys with prefix (sel_, buy_, lot_, etc.)
- Soft deletes via deleted_at column
- JSONB columns stored as TEXT (JSON) in SQLite; use JSONB in Postgres
"""

SCHEMA_SQL = """
-- ============================================================
-- ACCOUNTS
-- ============================================================

CREATE TABLE IF NOT EXISTS sellers (
    seller_id TEXT PRIMARY KEY,                -- sel_<uuid7>
    status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
        CHECK (status IN ('PENDING_VERIFICATION','ACTIVE','SUSPENDED','DEACTIVATED')),
    seller_type TEXT NOT NULL
        CHECK (seller_type IN ('retailer','brand','3pl','liquidator','other')),

    business_name TEXT NOT NULL,
    dba_name TEXT,
    ein_tin TEXT,                              -- encrypted in production
    state_of_incorporation TEXT,

    primary_contact_name TEXT NOT NULL,
    primary_contact_email TEXT NOT NULL,
    primary_contact_phone TEXT,

    warehouse_locations TEXT DEFAULT '[]',     -- JSON array; Postgres: JSONB
    payment_info TEXT DEFAULT '{}',            -- JSON; sensitive fields vault-referenced
    compliance TEXT DEFAULT '{}',              -- JSON: kyb_status, w9, aml, stolen_goods

    quality_score INTEGER DEFAULT 50,          -- 0-100
    total_transactions INTEGER DEFAULT 0,
    total_gmv_cents INTEGER DEFAULT 0,
    dispute_rate_pct REAL DEFAULT 0.0,
    avg_condition_accuracy_pct REAL DEFAULT 100.0,
    avg_ship_time_hours REAL DEFAULT 0.0,

    estimated_monthly_volume_cents INTEGER DEFAULT 0,
    estimated_monthly_pallets INTEGER DEFAULT 0,

    auto_accept_rules TEXT DEFAULT '[]',       -- JSON array
    payout_schedule TEXT DEFAULT 'T+3',

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    verified_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sellers_status ON sellers(status);
CREATE INDEX IF NOT EXISTS idx_sellers_type ON sellers(seller_type);
CREATE INDEX IF NOT EXISTS idx_sellers_quality ON sellers(quality_score);
CREATE INDEX IF NOT EXISTS idx_sellers_created ON sellers(created_at);

CREATE TABLE IF NOT EXISTS buyers (
    buyer_id TEXT PRIMARY KEY,                 -- buy_<uuid7>
    org_id TEXT,                               -- FK to buyer_orgs (nullable, V2)
    status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
        CHECK (status IN ('PENDING_VERIFICATION','ACTIVE','SUSPENDED','DEACTIVATED')),
    buyer_type TEXT NOT NULL
        CHECK (buyer_type IN ('ecom_reseller','discount_chain','exporter','bin_store','wholesaler')),

    business_name TEXT NOT NULL,
    ein_tin TEXT,
    resale_certificate TEXT DEFAULT '{}',      -- JSON: number, state, expires_at, verified

    primary_contact_name TEXT NOT NULL,
    primary_contact_email TEXT NOT NULL,
    primary_contact_phone TEXT,

    sales_channels TEXT DEFAULT '[]',          -- JSON array of channel enums
    primary_channel TEXT,

    warehouses TEXT DEFAULT '[]',              -- JSON array
    payment_info TEXT DEFAULT '{}',            -- JSON

    compliance TEXT DEFAULT '{}',              -- JSON: kyb, fraud, aml

    trust_score INTEGER DEFAULT 50,
    total_transactions INTEGER DEFAULT 0,
    total_gmv_cents INTEGER DEFAULT 0,
    dispute_rate_pct REAL DEFAULT 0.0,
    payment_default_count INTEGER DEFAULT 0,

    purchase_limit_cents INTEGER DEFAULT 500000,    -- $5,000 default
    purchase_limit_remaining_cents INTEGER DEFAULT 500000,
    estimated_monthly_volume_cents INTEGER DEFAULT 0,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    verified_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_buyers_status ON buyers(status);
CREATE INDEX IF NOT EXISTS idx_buyers_type ON buyers(buyer_type);
CREATE INDEX IF NOT EXISTS idx_buyers_trust ON buyers(trust_score);
CREATE INDEX IF NOT EXISTS idx_buyers_created ON buyers(created_at);

CREATE TABLE IF NOT EXISTS buyer_orgs (
    org_id TEXT PRIMARY KEY,                   -- borg_<uuid>
    org_name TEXT NOT NULL,
    owner_buyer_id TEXT NOT NULL,
    shared_purchase_limit_cents INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (owner_buyer_id) REFERENCES buyers(buyer_id)
);

CREATE TABLE IF NOT EXISTS buyer_intent_profiles (
    profile_id TEXT PRIMARY KEY,               -- bip_<uuid>
    buyer_id TEXT NOT NULL,
    profile_name TEXT NOT NULL DEFAULT 'Default',
    is_active INTEGER NOT NULL DEFAULT 1,      -- boolean

    category_filters TEXT DEFAULT '{}',        -- JSON: {include:[], exclude:[]}
    brand_filters TEXT DEFAULT '{}',           -- JSON: {preferred:[], excluded:[]}
    condition_min TEXT DEFAULT 'GOOD'
        CHECK (condition_min IN ('NEW','LIKE_NEW','GOOD','FAIR','SALVAGE')),

    channel_config TEXT DEFAULT '{}',          -- JSON
    economics TEXT DEFAULT '{}',               -- JSON: margin_target, max_lot_cost, etc.
    logistics TEXT DEFAULT '{}',               -- JSON: destination_zip, freight prefs
    trust_filters TEXT DEFAULT '{}',           -- JSON: min_seller_reputation, etc.
    automation TEXT DEFAULT '{}',              -- JSON: auto_bid settings
    notifications TEXT DEFAULT '{}',           -- JSON: methods, triggers

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id)
);
CREATE INDEX IF NOT EXISTS idx_bip_buyer ON buyer_intent_profiles(buyer_id);
CREATE INDEX IF NOT EXISTS idx_bip_active ON buyer_intent_profiles(is_active);

-- ============================================================
-- CATALOG
-- ============================================================

CREATE TABLE IF NOT EXISTS canonical_products (
    product_id TEXT PRIMARY KEY,               -- cprod_<uuid>

    upc TEXT,
    ean TEXT,
    asin TEXT,
    mpn TEXT,

    title TEXT NOT NULL,
    brand_raw TEXT,
    brand_normalized TEXT,
    manufacturer TEXT,

    department TEXT,
    category_l1 TEXT,
    category_l2 TEXT,
    category_l3 TEXT,

    attributes TEXT DEFAULT '{}',              -- JSON: color, size, weight, dimensions
    retail_price_cents INTEGER,
    msrp_cents INTEGER,

    resale_data TEXT DEFAULT '{}',             -- JSON: per-channel pricing + velocity
    restrictions TEXT DEFAULT '{}',            -- JSON: map, gating, hazmat, recall
    images TEXT DEFAULT '[]',                  -- JSON array
    data_sources TEXT DEFAULT '[]',            -- JSON array
    data_freshness TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_products_upc ON canonical_products(upc);
CREATE INDEX IF NOT EXISTS idx_products_asin ON canonical_products(asin);
CREATE INDEX IF NOT EXISTS idx_products_brand ON canonical_products(brand_normalized);
CREATE INDEX IF NOT EXISTS idx_products_cat1 ON canonical_products(category_l1);
CREATE INDEX IF NOT EXISTS idx_products_cat2 ON canonical_products(category_l2);

-- ============================================================
-- INGESTION
-- ============================================================

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id TEXT PRIMARY KEY,                   -- mfst_<uuid>
    seller_id TEXT NOT NULL,

    file_key TEXT NOT NULL,                    -- S3 path
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size_bytes INTEGER,
    file_hash_sha256 TEXT,

    status TEXT NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED','PROCESSING','EXTRACTED','NORMALIZED','COMPLETED','FAILED','NEEDS_REVIEW')),
    status_history TEXT DEFAULT '[]',          -- JSON array

    extraction_stats TEXT DEFAULT '{}',        -- JSON
    normalization_stats TEXT DEFAULT '{}',     -- JSON
    lot_ids_created TEXT DEFAULT '[]',         -- JSON array

    ship_from_location_id TEXT,
    seller_notes TEXT,
    default_condition TEXT DEFAULT 'LIKE_NEW',

    processing_time_ms INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_seller ON ingestion_jobs(seller_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingestion_jobs(created_at);

CREATE TABLE IF NOT EXISTS raw_line_items (
    raw_item_id TEXT PRIMARY KEY,              -- rli_<uuid>
    job_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,

    raw_fields TEXT NOT NULL DEFAULT '{}',     -- JSON: all extracted fields
    extraction_confidence TEXT DEFAULT '{}',   -- JSON: per-field confidence
    flags TEXT DEFAULT '{}',                   -- JSON: needs_review, review_fields

    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES ingestion_jobs(job_id)
);
CREATE INDEX IF NOT EXISTS idx_rli_job ON raw_line_items(job_id);

CREATE TABLE IF NOT EXISTS normalized_line_items (
    normalized_item_id TEXT PRIMARY KEY,        -- nli_<uuid>
    raw_item_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    lot_id TEXT,                               -- set when assigned to a lot

    product_id TEXT,                           -- FK to canonical_products (nullable if unmatched)
    match_type TEXT DEFAULT 'UNMATCHED'
        CHECK (match_type IN ('EXACT','HIGH','LOW','UNMATCHED')),
    match_confidence REAL DEFAULT 0.0,
    matched_on TEXT,                           -- 'asin', 'upc', 'fuzzy_title', etc.

    title TEXT,
    brand_normalized TEXT,
    category_l1 TEXT,
    category_l2 TEXT,
    category_l3 TEXT,

    condition_raw TEXT,
    condition_grade TEXT
        CHECK (condition_grade IN ('NEW','LIKE_NEW','GOOD','FAIR','SALVAGE')),

    quantity INTEGER NOT NULL DEFAULT 1,
    unit_cost_cents INTEGER DEFAULT 0,
    total_cost_cents INTEGER DEFAULT 0,
    retail_price_cents INTEGER,
    msrp_cents INTEGER,

    weight_oz INTEGER,
    dimensions TEXT DEFAULT '{}',              -- JSON
    resale_estimates TEXT DEFAULT '{}',        -- JSON: per-channel estimates
    restrictions TEXT DEFAULT '[]',            -- JSON array

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (raw_item_id) REFERENCES raw_line_items(raw_item_id),
    FOREIGN KEY (job_id) REFERENCES ingestion_jobs(job_id),
    FOREIGN KEY (product_id) REFERENCES canonical_products(product_id)
);
CREATE INDEX IF NOT EXISTS idx_nli_job ON normalized_line_items(job_id);
CREATE INDEX IF NOT EXISTS idx_nli_lot ON normalized_line_items(lot_id);
CREATE INDEX IF NOT EXISTS idx_nli_product ON normalized_line_items(product_id);
CREATE INDEX IF NOT EXISTS idx_nli_brand ON normalized_line_items(brand_normalized);

-- ============================================================
-- LOTS
-- ============================================================

CREATE TABLE IF NOT EXISTS lots (
    lot_id TEXT PRIMARY KEY,                   -- lot_<uuid>
    seller_id TEXT NOT NULL,
    job_id TEXT,

    status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT','ACTIVE','UNDER_CONTRACT','SOLD','EXPIRED','WITHDRAWN')),

    title TEXT NOT NULL,
    description TEXT,
    description_generated_by TEXT DEFAULT 'ai',

    -- Summary stats (denormalized for query performance)
    total_units INTEGER DEFAULT 0,
    total_skus INTEGER DEFAULT 0,
    total_weight_lb REAL DEFAULT 0.0,
    total_cube_cuft REAL DEFAULT 0.0,
    pallet_count INTEGER DEFAULT 0,
    packing_type TEXT DEFAULT 'pallet'
        CHECK (packing_type IN ('pallet','case_pack','gaylord','mixed','parcel')),
    estimated_retail_value_cents INTEGER DEFAULT 0,
    total_cost_cents INTEGER DEFAULT 0,
    recovery_rate_pct REAL DEFAULT 0.0,

    condition_distribution TEXT DEFAULT '{}',   -- JSON: {NEW: 0.65, LIKE_NEW: 0.30, ...}
    condition_primary TEXT
        CHECK (condition_primary IN ('NEW','LIKE_NEW','GOOD','FAIR','SALVAGE')),

    category_primary TEXT,
    categories TEXT DEFAULT '{}',              -- JSON: {primary, secondary[], department}
    top_brands TEXT DEFAULT '[]',              -- JSON array

    ship_from_zip TEXT,
    ship_from_state TEXT,
    ship_from_city TEXT,
    ship_from_location_id TEXT,

    -- Pricing
    pricing_mode TEXT DEFAULT 'MAKE_OFFER'
        CHECK (pricing_mode IN ('FIXED_PRICE','MAKE_OFFER','AUCTION')),
    ask_price_cents INTEGER,
    floor_price_cents INTEGER,
    recommended_ask_cents INTEGER,
    time_decay_schedule TEXT DEFAULT '{}',      -- JSON
    holding_cost_per_day_cents INTEGER DEFAULT 100,
    pricing_recommendation_id TEXT,

    -- Restrictions & requirements
    restrictions TEXT DEFAULT '[]',            -- JSON array
    buyer_requirements TEXT DEFAULT '{}',      -- JSON

    -- Media
    media TEXT DEFAULT '{}',                   -- JSON: {photos:[], videos:[], documents:[]}

    -- Stats
    views INTEGER DEFAULT 0,
    matches_sent INTEGER DEFAULT 0,
    offers_received INTEGER DEFAULT 0,
    days_active INTEGER DEFAULT 0,

    -- Expiry
    expires_at TEXT,
    auto_reprice_on_expiry INTEGER DEFAULT 1,  -- boolean
    reprice_reduction_pct REAL DEFAULT 10.0,

    created_at TEXT NOT NULL,
    activated_at TEXT,
    sold_at TEXT,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_lots_seller ON lots(seller_id);
CREATE INDEX IF NOT EXISTS idx_lots_status ON lots(status);
CREATE INDEX IF NOT EXISTS idx_lots_category ON lots(category_primary);
CREATE INDEX IF NOT EXISTS idx_lots_ask_price ON lots(ask_price_cents);
CREATE INDEX IF NOT EXISTS idx_lots_condition ON lots(condition_primary);
CREATE INDEX IF NOT EXISTS idx_lots_created ON lots(created_at);

CREATE TABLE IF NOT EXISTS lot_line_items (
    lot_line_item_id TEXT PRIMARY KEY,          -- lli_<uuid>
    lot_id TEXT NOT NULL,
    normalized_item_id TEXT NOT NULL,
    product_id TEXT,

    quantity INTEGER NOT NULL,
    condition_grade TEXT,
    unit_cost_cents INTEGER DEFAULT 0,
    retail_price_cents INTEGER,
    brand_normalized TEXT,
    category_l1 TEXT,

    resale_value_estimate_cents INTEGER,
    resale_channel TEXT,
    restrictions TEXT DEFAULT '[]',             -- JSON array

    sort_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id),
    FOREIGN KEY (normalized_item_id) REFERENCES normalized_line_items(normalized_item_id)
);
CREATE INDEX IF NOT EXISTS idx_lli_lot ON lot_line_items(lot_id);
CREATE INDEX IF NOT EXISTS idx_lli_product ON lot_line_items(product_id);

-- ============================================================
-- PRICING
-- ============================================================

CREATE TABLE IF NOT EXISTS pricing_recommendations (
    recommendation_id TEXT PRIMARY KEY,        -- prcrec_<uuid>
    lot_id TEXT NOT NULL,
    model_version TEXT NOT NULL,

    lot_valuation TEXT NOT NULL DEFAULT '{}',   -- JSON: blended + per-channel
    recommended_pricing TEXT NOT NULL DEFAULT '{}', -- JSON: ask, floor, clearing, confidence
    clearing_analysis TEXT DEFAULT '{}',        -- JSON: probabilities, holding cost, decay
    comparable_transactions TEXT DEFAULT '[]',  -- JSON array
    explanation TEXT,

    created_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id)
);
CREATE INDEX IF NOT EXISTS idx_prcrec_lot ON pricing_recommendations(lot_id);

CREATE TABLE IF NOT EXISTS margin_simulations (
    simulation_id TEXT PRIMARY KEY,            -- msim_<uuid>
    lot_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    profile_id TEXT,
    model_version TEXT NOT NULL,

    channel TEXT NOT NULL,
    destination_zip TEXT NOT NULL,
    purchase_price_cents INTEGER,

    revenue_estimate TEXT DEFAULT '{}',         -- JSON
    cost_breakdown TEXT DEFAULT '{}',           -- JSON
    margin_analysis TEXT DEFAULT '{}',          -- JSON: profit, margin%, roi%, confidence band
    risk_factors TEXT DEFAULT '[]',             -- JSON array
    explanation TEXT,

    created_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id)
);
CREATE INDEX IF NOT EXISTS idx_msim_lot ON margin_simulations(lot_id);
CREATE INDEX IF NOT EXISTS idx_msim_buyer ON margin_simulations(buyer_id);

-- ============================================================
-- OFFERS + NEGOTIATION
-- ============================================================

CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,                 -- off_<uuid>
    lot_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,

    offer_type TEXT NOT NULL
        CHECK (offer_type IN ('ACCEPT_ASK','MAKE_OFFER','CONDITIONAL_OFFER','AUTO_BID')),
    offered_price_cents INTEGER NOT NULL,
    conditions TEXT DEFAULT '[]',              -- JSON array
    buyer_message TEXT,
    simulation_id TEXT,                        -- margin sim that informed this offer

    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','ACCEPTED','DECLINED','EXPIRED','COUNTERED','VOIDED')),
    status_history TEXT DEFAULT '[]',          -- JSON array

    valid_until TEXT NOT NULL,
    counter_offer_id TEXT,                     -- FK to counter_offers if countered

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id)
);
CREATE INDEX IF NOT EXISTS idx_offers_lot ON offers(lot_id);
CREATE INDEX IF NOT EXISTS idx_offers_buyer ON offers(buyer_id);
CREATE INDEX IF NOT EXISTS idx_offers_status ON offers(status);
CREATE INDEX IF NOT EXISTS idx_offers_created ON offers(created_at);

CREATE TABLE IF NOT EXISTS counter_offers (
    counter_id TEXT PRIMARY KEY,               -- ctr_<uuid>
    offer_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,

    counter_price_cents INTEGER NOT NULL,
    counter_message TEXT,
    round_number INTEGER NOT NULL DEFAULT 1,

    status TEXT NOT NULL DEFAULT 'PENDING_BUYER'
        CHECK (status IN ('PENDING_BUYER','ACCEPTED','DECLINED','EXPIRED')),
    status_history TEXT DEFAULT '[]',

    valid_until TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (offer_id) REFERENCES offers(offer_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_counters_offer ON counter_offers(offer_id);
CREATE INDEX IF NOT EXISTS idx_counters_status ON counter_offers(status);

-- ============================================================
-- ORDERS + PAYMENTS
-- ============================================================

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,                 -- ord_<uuid>
    lot_id TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    counter_id TEXT,
    buyer_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'CREATED'
        CHECK (status IN ('CREATED','AWAITING_PAYMENT','AWAITING_SHIPMENT','SHIPPED',
                          'DELIVERED','INSPECTION','COMPLETED','CANCELLED','DISPUTED')),
    status_history TEXT DEFAULT '[]',

    -- Amounts (all in cents)
    lot_price_cents INTEGER NOT NULL,
    platform_fee_cents INTEGER NOT NULL,
    platform_fee_rate_pct REAL NOT NULL,
    freight_cost_cents INTEGER DEFAULT 0,
    insurance_cents INTEGER DEFAULT 0,
    processing_fee_cents INTEGER DEFAULT 0,
    total_buyer_cost_cents INTEGER NOT NULL,
    seller_payout_cents INTEGER NOT NULL,
    platform_revenue_cents INTEGER NOT NULL,

    escrow_id TEXT,
    shipment_id TEXT,
    invoice_id TEXT,

    inspection_window_opens_at TEXT,
    inspection_window_closes_at TEXT,
    inspection_result TEXT
        CHECK (inspection_result IS NULL OR inspection_result IN ('ACCEPTED','DISPUTED','PARTIAL_ACCEPT')),
    inspection_result_at TEXT,
    inspection_result_method TEXT,

    disputes TEXT DEFAULT '[]',                -- JSON array of dispute_ids

    created_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id),
    FOREIGN KEY (offer_id) REFERENCES offers(offer_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,               -- inv_<uuid>
    order_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    invoice_type TEXT NOT NULL DEFAULT 'buyer',

    line_items TEXT NOT NULL DEFAULT '[]',      -- JSON array
    subtotal_cents INTEGER NOT NULL,
    tax_cents INTEGER DEFAULT 0,
    total_cents INTEGER NOT NULL,

    tax_exempt INTEGER DEFAULT 0,              -- boolean
    resale_cert_number TEXT,
    pdf_url TEXT,

    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
CREATE INDEX IF NOT EXISTS idx_invoices_order ON invoices(order_id);

CREATE TABLE IF NOT EXISTS escrow_transactions (
    escrow_id TEXT PRIMARY KEY,                -- esc_<uuid>
    order_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,

    lot_price_cents INTEGER NOT NULL,
    platform_fee_cents INTEGER NOT NULL,
    freight_cost_cents INTEGER DEFAULT 0,
    insurance_cents INTEGER DEFAULT 0,
    total_cents INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'PENDING_FUNDING'
        CHECK (status IN ('PENDING_FUNDING','FUNDED','HELD','PARTIALLY_RELEASED',
                          'RELEASED','REFUNDED','VOIDED')),
    status_history TEXT DEFAULT '[]',

    funding_method TEXT,
    funding_amount_cents INTEGER,
    funding_reference TEXT,
    funding_processor TEXT DEFAULT 'stripe',
    funding_processor_txn_id TEXT,
    funded_at TEXT,

    holds TEXT DEFAULT '[]',                   -- JSON array
    releases TEXT DEFAULT '[]',                -- JSON array

    funding_deadline TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_escrow_order ON escrow_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_escrow_status ON escrow_transactions(status);

CREATE TABLE IF NOT EXISTS payouts (
    payout_id TEXT PRIMARY KEY,                -- pay_<uuid>
    escrow_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,

    amount_cents INTEGER NOT NULL,
    method TEXT DEFAULT 'ach',
    destination_account_last4 TEXT,
    processor TEXT DEFAULT 'stripe',
    processor_payout_id TEXT,

    status TEXT NOT NULL DEFAULT 'INITIATED'
        CHECK (status IN ('INITIATED','PROCESSING','COMPLETED','FAILED')),
    status_history TEXT DEFAULT '[]',

    expected_arrival_date TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (escrow_id) REFERENCES escrow_transactions(escrow_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_payouts_seller ON payouts(seller_id);
CREATE INDEX IF NOT EXISTS idx_payouts_status ON payouts(status);

-- ============================================================
-- FREIGHT
-- ============================================================

CREATE TABLE IF NOT EXISTS carrier_quotes (
    quote_id TEXT PRIMARY KEY,                 -- frt_<uuid>
    lot_id TEXT NOT NULL,
    requested_by TEXT,

    origin_zip TEXT NOT NULL,
    destination_zip TEXT NOT NULL,

    shipment_specs TEXT NOT NULL DEFAULT '{}', -- JSON: mode, weight, pallets, class, accessorials
    options TEXT NOT NULL DEFAULT '[]',         -- JSON array of carrier options
    selected_option_index INTEGER,
    quote_provider TEXT DEFAULT 'shipengine',
    provider_quote_id TEXT,

    created_at TEXT NOT NULL,
    FOREIGN KEY (lot_id) REFERENCES lots(lot_id)
);
CREATE INDEX IF NOT EXISTS idx_quotes_lot ON carrier_quotes(lot_id);
CREATE INDEX IF NOT EXISTS idx_quotes_lane ON carrier_quotes(origin_zip, destination_zip);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id TEXT PRIMARY KEY,              -- shp_<uuid>
    order_id TEXT NOT NULL,
    quote_id TEXT,

    origin_zip TEXT NOT NULL,
    origin_city TEXT,
    origin_state TEXT,
    destination_zip TEXT NOT NULL,
    destination_city TEXT,
    destination_state TEXT,

    freight_details TEXT DEFAULT '{}',          -- JSON: mode, class, weight, pallets, dims
    accessorials TEXT DEFAULT '{}',             -- JSON

    carrier_name TEXT,
    carrier_scac TEXT,
    carrier_service TEXT,

    cost_cents INTEGER DEFAULT 0,
    insurance_cents INTEGER DEFAULT 0,

    tracking_number TEXT,
    pro_number TEXT,
    bol_document_url TEXT,

    pickup_scheduled_date TEXT,
    pickup_time_window TEXT,
    pickup_confirmed_at TEXT,

    delivery_estimated_date TEXT,
    delivery_actual_date TEXT,
    delivery_delivered_at TEXT,
    delivery_pod_url TEXT,
    delivery_signed_by TEXT,

    status TEXT NOT NULL DEFAULT 'BOOKED'
        CHECK (status IN ('QUOTE_REQUESTED','BOOKED','PICKUP_SCHEDULED','PICKED_UP',
                          'IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED','EXCEPTION','RETURNED')),
    status_history TEXT DEFAULT '[]',

    booked_via TEXT,
    booking_reference TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
CREATE INDEX IF NOT EXISTS idx_shipments_order ON shipments(order_id);
CREATE INDEX IF NOT EXISTS idx_shipments_status ON shipments(status);
CREATE INDEX IF NOT EXISTS idx_shipments_carrier ON shipments(carrier_name);

CREATE TABLE IF NOT EXISTS tracking_events (
    event_id TEXT PRIMARY KEY,                 -- trk_<uuid>
    shipment_id TEXT NOT NULL,

    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    location_city TEXT,
    location_state TEXT,
    location_zip TEXT,
    description TEXT,
    source TEXT DEFAULT 'carrier_api',
    raw_event TEXT DEFAULT '{}',               -- JSON

    created_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipments(shipment_id)
);
CREATE INDEX IF NOT EXISTS idx_tracking_shipment ON tracking_events(shipment_id);
CREATE INDEX IF NOT EXISTS idx_tracking_timestamp ON tracking_events(timestamp);

CREATE TABLE IF NOT EXISTS lanes (
    lane_id TEXT PRIMARY KEY,                  -- lane_<origin>_<dest>
    origin_zip TEXT NOT NULL,
    destination_zip TEXT NOT NULL,
    origin_state TEXT,
    destination_state TEXT,
    mode TEXT DEFAULT 'LTL',
    distance_miles REAL,

    pricing_stats TEXT DEFAULT '{}',           -- JSON: avg, median, min, max per pallet
    preferred_carriers TEXT DEFAULT '[]',      -- JSON array

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lanes_route ON lanes(origin_zip, destination_zip);

-- ============================================================
-- DISPUTES
-- ============================================================

CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY,               -- dsp_<uuid>
    order_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    buyer_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    escrow_id TEXT,

    type TEXT NOT NULL
        CHECK (type IN ('CONDITION_MISMATCH','MISSING_UNITS','WRONG_ITEMS',
                        'DAMAGE_IN_TRANSIT','COUNTERFEIT')),
    description TEXT NOT NULL,
    affected_units INTEGER DEFAULT 0,
    total_units INTEGER DEFAULT 0,
    claimed_amount_cents INTEGER NOT NULL,

    buyer_evidence TEXT DEFAULT '[]',          -- JSON array
    seller_response TEXT DEFAULT '{}',         -- JSON

    status TEXT NOT NULL DEFAULT 'OPENED'
        CHECK (status IN ('OPENED','SELLER_RESPONDED','UNDER_REVIEW','RESOLVED','ESCALATED','CLOSED')),
    status_history TEXT DEFAULT '[]',

    resolution_id TEXT,

    seller_response_deadline TEXT,
    resolution_deadline TEXT,

    opened_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);
CREATE INDEX IF NOT EXISTS idx_disputes_order ON disputes(order_id);
CREATE INDEX IF NOT EXISTS idx_disputes_buyer ON disputes(buyer_id);
CREATE INDEX IF NOT EXISTS idx_disputes_seller ON disputes(seller_id);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);
CREATE INDEX IF NOT EXISTS idx_disputes_type ON disputes(type);

CREATE TABLE IF NOT EXISTS resolutions (
    resolution_id TEXT PRIMARY KEY,            -- res_<uuid>
    dispute_id TEXT NOT NULL,
    order_id TEXT NOT NULL,

    resolved_by TEXT NOT NULL,
    resolver_user_id TEXT,

    resolution_type TEXT NOT NULL
        CHECK (resolution_type IN ('FULL_REFUND','PARTIAL_REFUND','NO_REFUND','REPLACEMENT','CREDIT')),
    refund_amount_cents INTEGER DEFAULT 0,
    refund_to TEXT DEFAULT 'buyer',

    reasoning TEXT NOT NULL,
    financial_actions TEXT DEFAULT '[]',        -- JSON array
    reputation_impacts TEXT DEFAULT '[]',       -- JSON array
    follow_up_actions TEXT DEFAULT '[]',        -- JSON array

    created_at TEXT NOT NULL,
    FOREIGN KEY (dispute_id) REFERENCES disputes(dispute_id)
);
CREATE INDEX IF NOT EXISTS idx_resolutions_dispute ON resolutions(dispute_id);

-- ============================================================
-- REPUTATION
-- ============================================================

CREATE TABLE IF NOT EXISTS reputation_events (
    reputation_event_id TEXT PRIMARY KEY,       -- rep_<uuid>
    entity_type TEXT NOT NULL CHECK (entity_type IN ('seller','buyer')),
    entity_id TEXT NOT NULL,

    event_type TEXT NOT NULL
        CHECK (event_type IN ('ORDER_COMPLETED','DISPUTE_FILED','DISPUTE_RESOLVED_FAVOR',
                              'DISPUTE_RESOLVED_AGAINST','PAYMENT_DEFAULT','SHIPMENT_LATE',
                              'CONDITION_VERIFIED')),
    order_id TEXT,
    dispute_id TEXT,

    score_before INTEGER NOT NULL,
    score_delta INTEGER NOT NULL,
    score_after INTEGER NOT NULL,

    details TEXT DEFAULT '{}',                 -- JSON
    scoring_model_version TEXT,
    scoring_factors TEXT DEFAULT '{}',         -- JSON

    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rep_entity ON reputation_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_rep_type ON reputation_events(event_type);
CREATE INDEX IF NOT EXISTS idx_rep_created ON reputation_events(created_at);

-- ============================================================
-- AUDIT LOG (append-only)
-- ============================================================

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id TEXT PRIMARY KEY,                 -- aud_<uuid>
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    event TEXT NOT NULL,

    old_state TEXT,                            -- JSON
    new_state TEXT,                            -- JSON

    actor_type TEXT NOT NULL,                  -- 'buyer', 'seller', 'ops', 'system'
    actor_id TEXT NOT NULL,

    metadata TEXT DEFAULT '{}',                -- JSON
    timestamp TEXT NOT NULL,
    service TEXT,
    trace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
"""
