# LiquidityOS — Backend Codebase

AI-native B2B wholesale liquidation marketplace infrastructure.

## What This Is

A fully functional Python/Flask backend implementing the LiquidityOS commerce API. This codebase covers **Weeks 1–8 of the MVP plan**: database schema, account management, lot creation/activation, pricing engine, margin simulation, offer/negotiation flow, and order creation.

## Architecture

```
app/
├── main.py              # Flask application entry point
├── db.py                # Database connection + helpers (SQLite dev / Postgres prod)
├── middleware/
│   └── auth.py          # JWT authentication + role-based authorization
├── routes/
│   └── api.py           # All REST API endpoints (/v1/*)
├── services/
│   ├── audit.py         # Immutable audit log
│   ├── sellers.py       # Seller registration, verification, management
│   ├── buyers.py        # Buyer registration, intent profiles
│   ├── lots.py          # Lot creation, activation, search
│   ├── pricing.py       # V1 pricing engine + margin simulation
│   └── offers.py        # Offer/counter-offer/accept flow + order creation
├── utils/
│   └── helpers.py       # ID generation, timestamps, constants
└── agent/               # LLM agent (placeholder for Week 11)

migrations/
└── schema.py            # Full database schema (26 tables, all indexes)

scripts/
└── seed.py              # Seed data + end-to-end transaction test
```

## Database

26 tables implementing the complete data model from Section 4:
- **Accounts**: sellers, buyers, buyer_orgs, buyer_intent_profiles
- **Catalog**: canonical_products
- **Ingestion**: ingestion_jobs, raw_line_items, normalized_line_items
- **Lots**: lots, lot_line_items
- **Pricing**: pricing_recommendations, margin_simulations
- **Offers**: offers, counter_offers
- **Orders**: orders, invoices, escrow_transactions, payouts
- **Freight**: carrier_quotes, shipments, tracking_events, lanes
- **Trust**: disputes, resolutions, reputation_events
- **Audit**: audit_log (append-only)

## API Endpoints (40+)

| Domain | Endpoints |
|--------|-----------|
| Auth | POST /v1/auth/token |
| Sellers | POST/GET /v1/sellers, GET/PUT /v1/sellers/me |
| Buyers | POST/GET /v1/buyers, GET /v1/buyers/me |
| Intent Profiles | POST/GET/PUT /v1/buyers/me/intent-profiles |
| Lots | POST/GET /v1/lots, POST /v1/lots/:id/activate |
| Pricing | GET /v1/lots/:id/pricing, POST /v1/lots/:id/margin-simulation |
| Offers | POST/GET /v1/offers, POST /accept/counter/decline |
| Orders | GET /v1/orders, GET /v1/orders/:id |
| Admin | GET /v1/admin/dashboard, POST verify sellers/buyers |

## Quick Start

```bash
# Run the seed script (creates DB + test data + executes full transaction flow)
python3 scripts/seed.py

# Start the API server
python3 app/main.py

# Or test with Flask test client
python3 -c "from app.main import app; client = app.test_client(); print(client.get('/v1/health').get_json())"
```

## What the Seed Script Demonstrates

A complete end-to-end transaction flow:
1. Register + verify a seller (PalletPros LLC)
2. Register + verify a buyer (FlipKing Ventures)
3. Create buyer intent profile (home & kitchen, 35% margin target)
4. Seed canonical products (Instant Pot, Ninja, KitchenAid)
5. Create a lot (127 units, 2 pallets, Mixed Home & Kitchen)
6. Activate lot with pricing ($2,800 ask, $2,200 floor)
7. Compute margin simulation (45% margin on Amazon FBA)
8. Buyer places offer ($2,400)
9. Seller counters ($2,600)
10. Buyer accepts counter → Order created ($3,050 total, $234 platform revenue)

All with full audit trail (11 events logged).

## Production Migration Path

This codebase uses SQLite for zero-dependency development. For production:

1. **Database**: Swap `app/db.py` to use `psycopg2` or `asyncpg` for PostgreSQL
2. **Auth**: Add proper JWT expiry, refresh tokens, password hashing
3. **Payments**: Integrate Stripe Connect (escrow via payment intents)
4. **Freight**: Integrate ShipEngine API (carrier quotes + booking)
5. **LLM Agent**: Add Claude Sonnet integration with tool-use (Week 11)
6. **File Upload**: Add S3 integration for manifest uploads
7. **Deploy**: Containerize with Docker, deploy to ECS/Railway

## Dependencies

- Python 3.12+
- Flask 3.1+
- PyJWT 2.7+
- SQLite (built-in)

No external package installation required — all dependencies are standard library or pre-installed.
