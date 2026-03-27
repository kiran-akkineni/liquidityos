"""
Utility functions for LiquidityOS.
"""

import uuid
import json
from datetime import datetime, timezone


def make_id(prefix: str) -> str:
    """Generate a prefixed UUID. In production, use UUIDv7 for time-sortability."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_dumps(obj) -> str:
    """Serialize to compact JSON string for DB storage."""
    return json.dumps(obj, separators=(",", ":"), default=str)


def parse_json_field(value):
    """Safely parse a JSON string, returning the original if it fails."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def cents_to_dollars(cents: int) -> float:
    return round(cents / 100, 2) if cents else 0.0


def dollars_to_cents(dollars: float) -> int:
    return int(round(dollars * 100))


CONDITION_ORDER = {"NEW": 5, "LIKE_NEW": 4, "GOOD": 3, "FAIR": 2, "SALVAGE": 1}

CONDITION_MULTIPLIERS = {
    "NEW": 1.0,
    "LIKE_NEW": 0.85,
    "GOOD": 0.70,
    "FAIR": 0.50,
    "SALVAGE": 0.25,
}

CHANNEL_FEES = {
    "amazon_fba": {"referral_pct": 0.15, "fulfillment_per_unit_cents": 450, "returns_pct": 0.05, "storage_per_cuft_month_cents": 83},
    "amazon_fbm": {"referral_pct": 0.15, "returns_pct": 0.03},
    "ebay": {"final_value_pct": 0.1325, "returns_pct": 0.03},
    "walmart": {"referral_pct": 0.10, "returns_pct": 0.04},
    "bin_store": {"markup_pct": 0.15, "returns_pct": 0.01},
}

PLATFORM_FEE_PCT = 0.09
INSURANCE_PCT = 0.01
PREP_COST_PER_UNIT_CENTS = {"amazon_fba": 150, "amazon_fbm": 50, "ebay": 50, "walmart": 50, "bin_store": 0}
