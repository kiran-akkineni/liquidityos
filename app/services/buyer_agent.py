"""
LLM Buyer Agent — autonomous lot evaluation, offer generation, and counter-offer decisions.

The agent acts on behalf of a buyer, using their intent profile to:
1. Score lots against profile criteria (category, brand, condition, economics)
2. Run margin simulations and assess profitability
3. Generate offers with strategy reasoning
4. Decide on counter-offers (accept, counter-back, or walk away)

This is a rule-based "LLM-like" agent for V1 — structured to plug in
actual LLM calls (Claude API) in V2 for natural language reasoning.
"""

import json
from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import (
    make_id, now_iso, json_dumps, cents_to_dollars,
    CONDITION_ORDER, PLATFORM_FEE_PCT,
)
from app.services.audit import log_event
from app.services import buyers, lots, pricing, offers


# ── Lot evaluation ─────────────────────────────────────────────────────

def evaluate_lot(buyer_id: str, lot_id: str, profile_id: str = None) -> dict:
    """Evaluate a lot against a buyer's intent profile.
    Returns a scored assessment with match signals and a recommendation."""
    buyer = buyers.get_buyer(buyer_id)
    if not buyer or buyer["status"] != "ACTIVE":
        return {"error": "BUYER_NOT_ACTIVE"}

    lot = lots.get_lot(lot_id)
    if not lot or lot["status"] != "ACTIVE":
        return {"error": "LOT_NOT_AVAILABLE"}

    # Get profile (use specified or first active)
    profile = _get_profile(buyer_id, profile_id)
    if not profile:
        return {"error": "NO_INTENT_PROFILE"}

    # Score each dimension
    category_score = _score_category(lot, profile)
    brand_score = _score_brands(lot, profile)
    condition_score = _score_condition(lot, profile)
    economics_score = _score_economics(lot, profile, buyer)
    logistics_score = _score_logistics(lot, profile)

    # Weighted composite
    weights = {
        "category": 0.20,
        "brand": 0.15,
        "condition": 0.15,
        "economics": 0.35,
        "logistics": 0.15,
    }
    composite = sum(
        weights[k] * v["score"]
        for k, v in {
            "category": category_score,
            "brand": brand_score,
            "condition": condition_score,
            "economics": economics_score,
            "logistics": logistics_score,
        }.items()
    )
    composite = round(composite, 2)

    # Generate recommendation
    if composite >= 0.75:
        action = "STRONG_BUY"
        reasoning = _build_reasoning(lot, profile, composite, "strong buy", category_score, brand_score, economics_score)
    elif composite >= 0.55:
        action = "BUY"
        reasoning = _build_reasoning(lot, profile, composite, "buy", category_score, brand_score, economics_score)
    elif composite >= 0.35:
        action = "CONSIDER"
        reasoning = _build_reasoning(lot, profile, composite, "consider with caution", category_score, brand_score, economics_score)
    else:
        action = "PASS"
        reasoning = _build_reasoning(lot, profile, composite, "pass", category_score, brand_score, economics_score)

    # Run margin simulation if economics look viable
    margin_sim = None
    if composite >= 0.35:
        channel = (profile.get("channel_config") or {}).get("primary_margin_channel", "amazon_fba")
        dest_zip = (profile.get("logistics") or {}).get("destination_zip", "90001")
        purchase_price = lot.get("ask_price_cents") or 0
        margin_sim = pricing.compute_margin_simulation(
            lot_id, buyer_id, channel, dest_zip, purchase_price
        )

    evaluation = {
        "evaluation_id": make_id("eval_"),
        "buyer_id": buyer_id,
        "lot_id": lot_id,
        "profile_id": profile.get("profile_id"),
        "composite_score": composite,
        "action": action,
        "reasoning": reasoning,
        "scores": {
            "category": category_score,
            "brand": brand_score,
            "condition": condition_score,
            "economics": economics_score,
            "logistics": logistics_score,
        },
        "margin_simulation": margin_sim,
        "lot_summary": {
            "title": lot["title"],
            "ask_price_cents": lot.get("ask_price_cents"),
            "total_units": lot.get("total_units"),
            "condition_primary": lot.get("condition_primary"),
            "top_brands": lot.get("top_brands", []),
            "category_primary": lot.get("category_primary"),
        },
        "created_at": now_iso(),
    }

    log_event("agent", evaluation["evaluation_id"], "LotEvaluated", "system", buyer_id,
              new_state={"lot_id": lot_id, "composite_score": composite, "action": action},
              service="buyer-agent")

    return evaluation


# ── Auto-offer generation ──────────────────────────────────────────────

def generate_auto_offer(buyer_id: str, lot_id: str, profile_id: str = None,
                         execute: bool = False) -> dict:
    """Generate an optimal offer for a lot. If execute=True, place it automatically."""
    evaluation = evaluate_lot(buyer_id, lot_id, profile_id)
    if "error" in evaluation:
        return evaluation

    if evaluation["action"] == "PASS":
        return {
            "recommendation": "PASS",
            "reasoning": evaluation["reasoning"],
            "evaluation": evaluation,
        }

    lot = lots.get_lot(lot_id)
    ask = lot.get("ask_price_cents", 0)
    floor = lot.get("floor_price_cents", 0)

    # Determine offer price based on evaluation strength
    composite = evaluation["composite_score"]
    margin_sim = evaluation.get("margin_simulation")

    offer_strategy = _compute_offer_strategy(composite, ask, floor, margin_sim, evaluation)

    result = {
        "recommendation": "OFFER",
        "offer_price_cents": offer_strategy["price"],
        "offer_type": offer_strategy["type"],
        "strategy": offer_strategy["strategy"],
        "reasoning": offer_strategy["reasoning"],
        "evaluation": evaluation,
    }

    # Execute if requested
    if execute and offer_strategy["price"] > 0:
        offer_result = offers.create_offer(buyer_id, {
            "lot_id": lot_id,
            "offer_type": offer_strategy["type"],
            "offered_price_cents": offer_strategy["price"],
            "message": offer_strategy["reasoning"],
        })
        if "error" not in offer_result:
            result["offer"] = offer_result
            result["executed"] = True
            log_event("agent", make_id("aoff_"), "AutoOfferPlaced", "system", buyer_id,
                      new_state={"lot_id": lot_id, "price": offer_strategy["price"],
                                 "strategy": offer_strategy["strategy"]},
                      service="buyer-agent")
        else:
            result["offer_error"] = offer_result
            result["executed"] = False

    return result


# ── Counter-offer decision ─────────────────────────────────────────────

def decide_counter(buyer_id: str, counter_id: str, profile_id: str = None) -> dict:
    """Decide whether to accept, counter-back, or decline a seller's counter-offer."""
    from app.services.offers import get_counter, get_offer

    counter = get_counter(counter_id)
    if not counter:
        return {"error": "COUNTER_NOT_FOUND"}
    if counter["status"] != "PENDING_BUYER":
        return {"error": "COUNTER_NOT_PENDING"}

    offer = get_offer(counter["offer_id"])
    lot = lots.get_lot(counter["lot_id"])
    profile = _get_profile(buyer_id, profile_id)

    counter_price = counter["counter_price_cents"]
    original_offer = offer["offered_price_cents"]
    ask_price = lot.get("ask_price_cents", 0)

    # Run margin sim at counter price
    channel = (profile.get("channel_config") or {}).get("primary_margin_channel", "amazon_fba") if profile else "amazon_fba"
    dest_zip = (profile.get("logistics") or {}).get("destination_zip", "90001") if profile else "90001"
    margin_sim = pricing.compute_margin_simulation(
        lot["lot_id"], buyer_id, channel, dest_zip, counter_price
    )

    margin_pct = 0
    if margin_sim and "margin_analysis" in margin_sim:
        ma = margin_sim["margin_analysis"]
        margin_pct = ma.get("margin_pct", 0)

    # Target margin from profile
    target_margin = 35
    if profile:
        econ = profile.get("economics") or {}
        target_margin = econ.get("margin_target_pct", 35)

    # Decision logic
    gap_from_original = counter_price - original_offer
    gap_pct = (gap_from_original / max(original_offer, 1)) * 100

    if margin_pct >= target_margin:
        decision = "ACCEPT"
        reasoning = (
            f"Counter of ${cents_to_dollars(counter_price):,.2f} yields {margin_pct:.1f}% margin, "
            f"which meets the {target_margin}% target. Accepting."
        )
    elif margin_pct >= target_margin * 0.85:
        # Close enough — accept if gap is reasonable
        if gap_pct <= 15:
            decision = "ACCEPT"
            reasoning = (
                f"Counter of ${cents_to_dollars(counter_price):,.2f} yields {margin_pct:.1f}% margin, "
                f"slightly below {target_margin}% target but within tolerance. "
                f"Gap from our offer is only {gap_pct:.0f}%. Accepting."
            )
        else:
            # Propose split the difference
            split_price = (counter_price + original_offer) // 2
            decision = "COUNTER"
            reasoning = (
                f"Counter of ${cents_to_dollars(counter_price):,.2f} yields {margin_pct:.1f}% margin, "
                f"below {target_margin}% target. Proposing ${cents_to_dollars(split_price):,.2f} "
                f"(split the difference)."
            )
    elif margin_pct >= target_margin * 0.70:
        split_price = (counter_price + original_offer) // 2
        decision = "COUNTER"
        reasoning = (
            f"Counter of ${cents_to_dollars(counter_price):,.2f} yields only {margin_pct:.1f}% margin "
            f"vs {target_margin}% target. Counter-proposing ${cents_to_dollars(split_price):,.2f}."
        )
    else:
        decision = "DECLINE"
        reasoning = (
            f"Counter of ${cents_to_dollars(counter_price):,.2f} yields only {margin_pct:.1f}% margin, "
            f"well below {target_margin}% target. Walking away."
        )

    result = {
        "decision": decision,
        "counter_id": counter_id,
        "counter_price_cents": counter_price,
        "original_offer_cents": original_offer,
        "margin_at_counter_pct": round(margin_pct, 1),
        "target_margin_pct": target_margin,
        "reasoning": reasoning,
    }

    if decision == "COUNTER":
        result["suggested_counter_cents"] = (counter_price + original_offer) // 2

    log_event("agent", make_id("adec_"), "CounterDecisionMade", "system", buyer_id,
              new_state={"counter_id": counter_id, "decision": decision,
                         "margin_pct": round(margin_pct, 1)},
              service="buyer-agent")

    return result


# ── Lot recommendations scan ──────────────────────────────────────────

def scan_recommendations(buyer_id: str, profile_id: str = None, limit: int = 10) -> dict:
    """Scan all active lots and return ranked recommendations for a buyer."""
    profile = _get_profile(buyer_id, profile_id)
    if not profile:
        return {"error": "NO_INTENT_PROFILE"}

    # Get all active lots
    with get_db() as conn:
        lot_rows = conn.execute(
            "SELECT * FROM lots WHERE status = 'ACTIVE' AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    active_lots = rows_to_dicts(lot_rows)

    recommendations = []
    for lot in active_lots:
        eval_result = evaluate_lot(buyer_id, lot["lot_id"], profile.get("profile_id"))
        if "error" in eval_result:
            continue
        if eval_result["action"] != "PASS":
            recommendations.append({
                "lot_id": lot["lot_id"],
                "title": lot["title"],
                "ask_price_cents": lot.get("ask_price_cents"),
                "total_units": lot.get("total_units"),
                "composite_score": eval_result["composite_score"],
                "action": eval_result["action"],
                "reasoning": eval_result["reasoning"],
                "scores": eval_result["scores"],
            })

    # Sort by composite score descending
    recommendations.sort(key=lambda r: r["composite_score"], reverse=True)

    return {
        "buyer_id": buyer_id,
        "profile_id": profile.get("profile_id"),
        "lots_scanned": len(active_lots),
        "recommendations": recommendations[:limit],
        "scanned_at": now_iso(),
    }


# ── Internal scoring functions ─────────────────────────────────────────

def _get_profile(buyer_id: str, profile_id: str = None) -> dict:
    if profile_id:
        return buyers.get_intent_profile(profile_id)
    profiles = buyers.list_intent_profiles(buyer_id)
    return profiles[0] if profiles else None


def _score_category(lot: dict, profile: dict) -> dict:
    cat_filters = profile.get("category_filters") or {}
    include = cat_filters.get("include", [])
    exclude = cat_filters.get("exclude", [])
    lot_cat = (lot.get("category_primary") or "").lower()

    if lot_cat in [e.lower() for e in exclude]:
        return {"score": 0.0, "signal": "excluded_category", "detail": f"{lot_cat} is in exclusion list"}
    if not include:
        return {"score": 0.7, "signal": "no_preference", "detail": "No category filter set"}
    if lot_cat in [i.lower() for i in include]:
        return {"score": 1.0, "signal": "preferred_category", "detail": f"{lot_cat} matches preference"}
    return {"score": 0.3, "signal": "non_preferred", "detail": f"{lot_cat} not in preferred list"}


def _score_brands(lot: dict, profile: dict) -> dict:
    brand_filters = profile.get("brand_filters") or {}
    preferred = [b.lower() for b in brand_filters.get("preferred", [])]
    excluded = [b.lower() for b in brand_filters.get("excluded", [])]
    lot_brands = [b.lower() for b in (lot.get("top_brands") or [])]

    if not lot_brands:
        return {"score": 0.5, "signal": "unknown_brands", "detail": "No brand data on lot"}

    # Check for excluded brands
    excluded_found = [b for b in lot_brands if b in excluded]
    if excluded_found:
        return {"score": 0.1, "signal": "excluded_brands", "detail": f"Contains excluded: {', '.join(excluded_found)}"}

    if not preferred:
        return {"score": 0.6, "signal": "no_preference", "detail": "No brand preference set"}

    # Count how many lot brands match preferred
    matches = [b for b in lot_brands if b in preferred]
    match_ratio = len(matches) / max(len(lot_brands), 1)

    if match_ratio >= 0.5:
        return {"score": 0.95, "signal": "strong_brand_match", "detail": f"{len(matches)}/{len(lot_brands)} preferred brands"}
    elif match_ratio > 0:
        return {"score": 0.7, "signal": "partial_brand_match", "detail": f"{len(matches)}/{len(lot_brands)} preferred brands"}
    return {"score": 0.4, "signal": "no_brand_match", "detail": "No preferred brands in lot"}


def _score_condition(lot: dict, profile: dict) -> dict:
    min_condition = profile.get("condition_min", "GOOD")
    lot_condition = lot.get("condition_primary", "GOOD")

    lot_grade = CONDITION_ORDER.get(lot_condition, 3)
    min_grade = CONDITION_ORDER.get(min_condition, 3)

    if lot_grade >= min_grade:
        # Meets or exceeds minimum
        excess = lot_grade - min_grade
        score = min(0.7 + excess * 0.1, 1.0)
        return {"score": score, "signal": "condition_met", "detail": f"{lot_condition} meets min {min_condition}"}
    else:
        # Below minimum
        deficit = min_grade - lot_grade
        score = max(0.1, 0.5 - deficit * 0.15)
        return {"score": score, "signal": "condition_below_min", "detail": f"{lot_condition} below min {min_condition}"}


def _score_economics(lot: dict, profile: dict, buyer: dict) -> dict:
    econ = profile.get("economics") or {}
    max_lot_cost = econ.get("max_lot_cost_cents", 0)
    margin_target = econ.get("margin_target_pct", 35)

    ask = lot.get("ask_price_cents") or 0
    total_cost = ask + int(ask * PLATFORM_FEE_PCT) + 19000 + int(ask * 0.01)
    retail_value = lot.get("estimated_retail_value_cents") or 0

    signals = []

    # Purchase limit check
    remaining = buyer.get("purchase_limit_remaining_cents", 0)
    if total_cost > remaining:
        return {"score": 0.0, "signal": "exceeds_purchase_limit",
                "detail": f"Total ${cents_to_dollars(total_cost):,.0f} exceeds limit ${cents_to_dollars(remaining):,.0f}"}

    # Max lot cost check
    if max_lot_cost and ask > max_lot_cost:
        signals.append(f"ask ${cents_to_dollars(ask):,.0f} exceeds max ${cents_to_dollars(max_lot_cost):,.0f}")
        return {"score": 0.15, "signal": "exceeds_max_lot_cost", "detail": signals[0]}

    # Rough margin estimate
    if retail_value > 0:
        rough_margin = ((retail_value * 0.45) - total_cost) / max(retail_value * 0.45, 1) * 100
        if rough_margin >= margin_target:
            score = min(0.6 + (rough_margin - margin_target) / 100, 1.0)
            return {"score": round(score, 2), "signal": "margin_meets_target",
                    "detail": f"Est. margin ~{rough_margin:.0f}% vs {margin_target}% target"}
        elif rough_margin >= margin_target * 0.7:
            return {"score": 0.5, "signal": "margin_near_target",
                    "detail": f"Est. margin ~{rough_margin:.0f}% (target {margin_target}%)"}
        else:
            return {"score": 0.2, "signal": "margin_below_target",
                    "detail": f"Est. margin ~{rough_margin:.0f}% well below {margin_target}% target"}

    return {"score": 0.4, "signal": "insufficient_data", "detail": "Cannot estimate margin without retail value"}


def _score_logistics(lot: dict, profile: dict) -> dict:
    logistics = profile.get("logistics") or {}
    dest_zip = logistics.get("destination_zip", "")
    max_freight_pct = logistics.get("max_freight_cost_pct", 20)

    origin_zip = lot.get("ship_from_zip", "")

    if not dest_zip or not origin_zip:
        return {"score": 0.5, "signal": "no_logistics_data", "detail": "Missing zip codes"}

    # Simple proximity check (same first 3 digits = close)
    if origin_zip[:3] == dest_zip[:3]:
        return {"score": 1.0, "signal": "local_shipment", "detail": f"Same zone: {origin_zip} → {dest_zip}"}
    elif origin_zip[0] == dest_zip[0]:
        return {"score": 0.7, "signal": "regional_shipment", "detail": f"Same region: {origin_zip} → {dest_zip}"}
    else:
        return {"score": 0.4, "signal": "cross_country", "detail": f"Cross-country: {origin_zip} → {dest_zip}"}


def _compute_offer_strategy(composite: float, ask: int, floor: int,
                              margin_sim: dict, evaluation: dict) -> dict:
    """Determine optimal offer price and strategy."""
    margin_pct = 0
    if margin_sim and "margin_analysis" in margin_sim:
        margin_pct = margin_sim["margin_analysis"].get("margin_pct", 0)

    if composite >= 0.80 and margin_pct >= 40:
        # Strong buy — offer close to ask for speed
        price = int(ask * 0.95)
        return {
            "price": price,
            "type": "MAKE_OFFER",
            "strategy": "AGGRESSIVE",
            "reasoning": (
                f"Strong match (score {composite:.2f}) with excellent margin ({margin_pct:.1f}%). "
                f"Offering ${cents_to_dollars(price):,.2f} (95% of ask) to secure the deal quickly."
            ),
        }
    elif composite >= 0.65:
        # Good match — offer at a discount
        discount = 0.88 if margin_pct >= 35 else 0.82
        price = max(int(ask * discount), floor) if floor else int(ask * discount)
        return {
            "price": price,
            "type": "MAKE_OFFER",
            "strategy": "MODERATE",
            "reasoning": (
                f"Good match (score {composite:.2f}), margin at ask is {margin_pct:.1f}%. "
                f"Offering ${cents_to_dollars(price):,.2f} ({discount*100:.0f}% of ask) "
                f"to optimize margin while remaining competitive."
            ),
        }
    elif composite >= 0.35:
        # Marginal — low-ball
        discount = 0.75
        price = max(int(ask * discount), floor) if floor else int(ask * discount)
        return {
            "price": price,
            "type": "MAKE_OFFER",
            "strategy": "CONSERVATIVE",
            "reasoning": (
                f"Marginal match (score {composite:.2f}). "
                f"Offering ${cents_to_dollars(price):,.2f} ({discount*100:.0f}% of ask) — "
                f"only worth it at a significant discount."
            ),
        }
    else:
        return {
            "price": 0,
            "type": "PASS",
            "strategy": "PASS",
            "reasoning": f"Score {composite:.2f} too low to justify an offer.",
        }


def _build_reasoning(lot: dict, profile: dict, composite: float, action_word: str,
                      cat_score: dict, brand_score: dict, econ_score: dict) -> str:
    """Build human-readable reasoning for the evaluation."""
    parts = [
        f"Composite score: {composite:.2f} — recommendation: {action_word}.",
    ]

    if cat_score["score"] >= 0.8:
        parts.append(f"Category match: {cat_score['detail']}.")
    elif cat_score["score"] < 0.3:
        parts.append(f"Category concern: {cat_score['detail']}.")

    if brand_score["score"] >= 0.8:
        parts.append(f"Strong brands: {brand_score['detail']}.")
    elif brand_score["score"] < 0.3:
        parts.append(f"Brand issue: {brand_score['detail']}.")

    parts.append(f"Economics: {econ_score['detail']}.")

    return " ".join(parts)


def cents_to_dollars(v):
    return round(v / 100, 2) if v else 0.0
