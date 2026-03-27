"""
Pricing service — V1 rule-based resale price estimation, lot valuation,
margin simulation, and pricing recommendations.
"""

from app.db import get_db, dict_from_row
from app.utils.helpers import (
    make_id, now_iso, json_dumps,
    CONDITION_MULTIPLIERS, CHANNEL_FEES, PLATFORM_FEE_PCT,
    INSURANCE_PCT, PREP_COST_PER_UNIT_CENTS,
)


def estimate_resale_price(product: dict, condition: str, channel: str) -> dict:
    """
    V1 rule-based resale price estimation.
    Uses catalog data × condition multiplier.
    """
    multiplier = CONDITION_MULTIPLIERS.get(condition, 0.5)
    resale_data = product.get("resale_data", {})
    channel_data = resale_data.get(channel, {}) if isinstance(resale_data, dict) else {}

    # Try channel-specific price; fall back to retail
    base_price = (
        channel_data.get("current_listing_price_cents")
        or product.get("retail_price_cents")
        or product.get("msrp_cents")
        or 0
    )

    estimated_price = int(base_price * multiplier)
    sell_through = channel_data.get("avg_sell_through_days", 30)

    # Confidence based on data availability
    confidence = 0.85 if channel_data.get("current_listing_price_cents") else 0.50

    return {
        "estimated_sale_price_cents": estimated_price,
        "estimated_sell_through_days": sell_through,
        "confidence": confidence,
        "base_price_cents": base_price,
        "condition_multiplier": multiplier,
    }


def compute_lot_valuation(lot: dict, line_items: list) -> dict:
    """
    Compute lot-level valuation across channels.
    Aggregates per-item estimates.
    """
    channels = ["amazon_fba", "amazon_fbm", "ebay", "walmart", "bin_store"]
    valuation_by_channel = {}

    for channel in channels:
        total_value = 0
        total_confidence = 0
        item_count = 0

        for item in line_items:
            product = item.get("_product", {})
            condition = item.get("condition_grade", "GOOD")
            qty = item.get("quantity", 1)

            est = estimate_resale_price(product, condition, channel)
            total_value += est["estimated_sale_price_cents"] * qty
            total_confidence += est["confidence"]
            item_count += 1

        avg_confidence = total_confidence / max(item_count, 1)
        valuation_by_channel[channel] = {
            "value_cents": total_value,
            "confidence": round(avg_confidence, 2),
        }

    # Blended = weighted avg of top 2 channels by value
    sorted_channels = sorted(valuation_by_channel.items(), key=lambda x: x[1]["value_cents"], reverse=True)
    blended = int(sorted_channels[0][1]["value_cents"] * 0.6 + sorted_channels[1][1]["value_cents"] * 0.4)

    return {
        "blended_resale_value_cents": blended,
        "valuation_by_channel": valuation_by_channel,
    }


def generate_pricing_recommendation(lot_id: str) -> dict:
    """
    Generate a full pricing recommendation for a lot.
    """
    from app.services.lots import get_lot

    lot = get_lot(lot_id)
    if not lot:
        return None

    # Get line items with product data
    with get_db() as conn:
        items = conn.execute(
            """SELECT nli.*, cp.resale_data, cp.retail_price_cents as cp_retail,
                      cp.msrp_cents as cp_msrp
               FROM lot_line_items lli
               JOIN normalized_line_items nli ON lli.normalized_item_id = nli.normalized_item_id
               LEFT JOIN canonical_products cp ON nli.product_id = cp.product_id
               WHERE lli.lot_id = ?""",
            (lot_id,)
        ).fetchall()

    line_items = []
    for item in items:
        d = dict_from_row(item)
        d["_product"] = {
            "resale_data": d.get("resale_data", {}),
            "retail_price_cents": d.get("cp_retail") or d.get("retail_price_cents", 0),
            "msrp_cents": d.get("cp_msrp") or d.get("msrp_cents", 0),
        }
        line_items.append(d)

    valuation = compute_lot_valuation(lot, line_items)
    blended = valuation["blended_resale_value_cents"]

    # Pricing objective: maximize recovery × clearing probability
    # Rule: ask at 25-35% of blended resale value for returns lots
    recommended_ask = int(blended * 0.30)
    floor_price = int(blended * 0.22)
    expected_clearing = int(blended * 0.27)

    rec_id = make_id("prcrec_")
    ts = now_iso()

    rec = {
        "recommendation_id": rec_id,
        "lot_id": lot_id,
        "model_version": "pricing-v1.0",
        "lot_valuation": valuation,
        "recommended_pricing": {
            "ask_price_cents": recommended_ask,
            "floor_price_cents": floor_price,
            "expected_clearing_price_cents": expected_clearing,
            "confidence_band": {
                "p10_cents": int(expected_clearing * 0.75),
                "p50_cents": expected_clearing,
                "p90_cents": int(expected_clearing * 1.20),
            },
        },
        "clearing_analysis": {
            "probability_of_sale_7d": 0.65,
            "probability_of_sale_14d": 0.85,
            "probability_of_sale_30d": 0.95,
            "optimal_time_to_sell": "now",
            "holding_cost_per_day_cents": lot.get("holding_cost_per_day_cents", 100),
        },
        "comparable_transactions": [],  # V2: query recent sales in same category
        "explanation": f"Lot valued at blended resale of ${blended/100:,.0f}. "
                       f"Recommended ask: ${recommended_ask/100:,.0f} ({round(recommended_ask/max(blended,1)*100)}% recovery). "
                       f"Floor: ${floor_price/100:,.0f}.",
    }

    # Persist
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pricing_recommendations
               (recommendation_id, lot_id, model_version, lot_valuation,
                recommended_pricing, clearing_analysis, comparable_transactions,
                explanation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec_id, lot_id, rec["model_version"],
                json_dumps(rec["lot_valuation"]),
                json_dumps(rec["recommended_pricing"]),
                json_dumps(rec["clearing_analysis"]),
                json_dumps(rec["comparable_transactions"]),
                rec["explanation"], ts,
            ),
        )

    return rec


def compute_margin_simulation(lot_id: str, buyer_id: str, channel: str,
                               destination_zip: str, purchase_price_cents: int = None) -> dict:
    """
    Compute full margin simulation for a buyer on a specific lot.
    """
    from app.services.lots import get_lot

    lot = get_lot(lot_id)
    if not lot:
        return None

    purchase = purchase_price_cents or lot.get("ask_price_cents", 0)
    total_units = lot.get("total_units", 1)
    estimated_retail = lot.get("estimated_retail_value_cents", 0)

    # Revenue estimate (V1: simple multiplier from retail value × condition)
    condition = lot.get("condition_primary", "GOOD")
    channel_mult = CONDITION_MULTIPLIERS.get(condition, 0.5)

    # Estimate per-unit revenue by channel
    fees = CHANNEL_FEES.get(channel, {})
    avg_unit_retail = estimated_retail / max(total_units, 1)
    avg_sale_price = int(avg_unit_retail * channel_mult)

    units_unsellable = max(1, int(total_units * 0.05))  # 5% unsellable
    units_sellable = total_units - units_unsellable
    estimated_revenue = avg_sale_price * units_sellable

    # Costs
    platform_fee = int(purchase * PLATFORM_FEE_PCT)
    freight_cost = _estimate_freight(lot, destination_zip)
    insurance = int(purchase * INSURANCE_PCT)
    prep_per_unit = PREP_COST_PER_UNIT_CENTS.get(channel, 50)
    prep_cost = prep_per_unit * total_units

    # Channel fees
    referral_pct = fees.get("referral_pct", fees.get("final_value_pct", 0.12))
    channel_fees = int(estimated_revenue * referral_pct)
    if channel == "amazon_fba":
        channel_fees += fees.get("fulfillment_per_unit_cents", 450) * units_sellable

    returns_pct = fees.get("returns_pct", 0.05)
    returns_allowance = int(estimated_revenue * returns_pct)

    storage_fees = 0
    if channel == "amazon_fba":
        cube = lot.get("total_cube_cuft", 0) or (total_units * 0.5)
        months = 1.5  # avg storage time
        storage_fees = int(cube * fees.get("storage_per_cuft_month_cents", 83) * months)

    total_cost = purchase + platform_fee + freight_cost + insurance + prep_cost + channel_fees + returns_allowance + storage_fees
    gross_profit = estimated_revenue - total_cost
    margin_pct = round(gross_profit / max(estimated_revenue, 1) * 100, 1)
    roi_pct = round(gross_profit / max(purchase, 1) * 100, 1)

    sim_id = make_id("msim_")
    ts = now_iso()

    sim = {
        "simulation_id": sim_id,
        "lot_id": lot_id,
        "buyer_id": buyer_id,
        "channel": channel,
        "destination_zip": destination_zip,
        "purchase_price_cents": purchase,
        "revenue_estimate": {
            "estimated_revenue_cents": estimated_revenue,
            "units_sellable": units_sellable,
            "units_unsellable": units_unsellable,
            "avg_sale_price_cents": avg_sale_price,
            "sell_through_days": {"p10": 55, "p50": 32, "p90": 18},
            "confidence": 0.75,
        },
        "cost_breakdown": {
            "purchase_price_cents": purchase,
            "platform_fee_cents": platform_fee,
            "freight_cost_cents": freight_cost,
            "insurance_cents": insurance,
            "prep_cost_cents": prep_cost,
            "channel_fees_cents": channel_fees,
            "returns_allowance_cents": returns_allowance,
            "storage_fees_cents": storage_fees,
            "total_cost_cents": total_cost,
        },
        "margin_analysis": {
            "estimated_gross_profit_cents": gross_profit,
            "margin_pct": margin_pct,
            "roi_pct": roi_pct,
            "confidence_band": {
                "p10_profit_cents": int(gross_profit * 0.45),
                "p10_margin_pct": round(margin_pct * 0.45, 1),
                "p50_profit_cents": gross_profit,
                "p50_margin_pct": margin_pct,
                "p90_profit_cents": int(gross_profit * 1.55),
                "p90_margin_pct": round(margin_pct * 1.55, 1),
            },
            "breakeven_price_cents": total_cost,
        },
        "risk_factors": [],
        "explanation": f"Estimated {margin_pct}% margin on {channel}. "
                       f"Revenue: ${estimated_revenue/100:,.0f}, Total cost: ${total_cost/100:,.0f}.",
    }

    # Persist
    with get_db() as conn:
        conn.execute(
            """INSERT INTO margin_simulations
               (simulation_id, lot_id, buyer_id, model_version, channel,
                destination_zip, purchase_price_cents, revenue_estimate,
                cost_breakdown, margin_analysis, risk_factors, explanation, created_at)
               VALUES (?, ?, ?, 'margin-v1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sim_id, lot_id, buyer_id, channel, destination_zip, purchase,
                json_dumps(sim["revenue_estimate"]),
                json_dumps(sim["cost_breakdown"]),
                json_dumps(sim["margin_analysis"]),
                json_dumps(sim["risk_factors"]),
                sim["explanation"], ts,
            ),
        )

    return sim


def _estimate_freight(lot: dict, destination_zip: str) -> int:
    """V1 freight estimate: simple per-pallet rate × pallet count."""
    pallet_count = lot.get("pallet_count", 1) or 1
    # V1: flat $95/pallet for same-state, $150/pallet cross-state
    origin_state = lot.get("ship_from_state", "")
    # Rough heuristic
    rate_per_pallet = 9500 if origin_state else 15000
    return rate_per_pallet * pallet_count
