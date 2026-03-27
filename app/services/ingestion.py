"""
Manifest ingestion pipeline — parse seller inventory files, map columns,
match to canonical products, normalize fields, and assemble lots.

Supports XLSX and CSV. Column detection uses regex heuristics.
Product matching uses exact ASIN/UPC lookup then fuzzy title fallback.
"""

import os
import re
import json
import pandas as pd
from difflib import SequenceMatcher

from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import make_id, now_iso, json_dumps, PLATFORM_FEE_PCT
from app.services.audit import log_event

# ── Column mapping heuristics ──────────────────────────────────────────

COLUMN_PATTERNS = {
    "asin":        [r"\basin\b"],
    "upc":         [r"\bupc\b", r"\bbarcode\b", r"\bean\b"],
    "sku":         [r"\bsku\b", r"\bitem\s*#", r"\bitem\s*num", r"\bproduct\s*id\b"],
    "title":       [r"\bdesc", r"\btitle\b", r"\bitem\s*name\b", r"\bproduct\s*name\b", r"\bitem\s*desc"],
    "quantity":    [r"\bqty\b", r"\bquantity\b", r"\bunits\b", r"\bcount\b", r"\bpcs\b", r"\bpieces\b"],
    "unit_cost":   [r"\bunit\s*cost\b", r"\bcost\s*per\b", r"\bwholesale\b", r"\bunit\s*price\b"],
    "cost":        [r"\bcost\b", r"\bprice\b"],
    "condition":   [r"\bcondition\b", r"\bcond\b", r"\bgrade\b", r"\bitem\s*condition\b"],
    "retail":      [r"\bretail\b", r"\bmsrp\b", r"\blist\s*price\b", r"\bretail\s*value\b"],
    "brand":       [r"\bbrand\b", r"\bmanufacturer\b", r"\bmfg\b", r"\bvendor\b"],
    "category":    [r"\bcategor", r"\bcat\b", r"\bdept\b", r"\bdepartment\b", r"\btype\b"],
}

# cost is a fallback for unit_cost — only used if unit_cost isn't found
FIELD_PRIORITY = ["asin", "upc", "sku", "title", "quantity", "unit_cost", "condition",
                  "retail", "brand", "category"]

CONDITION_MAP = {
    "new": "NEW", "sealed": "NEW", "nib": "NEW", "new in box": "NEW",
    "bnib": "NEW", "brand new": "NEW", "factory sealed": "NEW",
    "like new": "LIKE_NEW", "open box": "LIKE_NEW", "opened": "LIKE_NEW",
    "likenew": "LIKE_NEW", "excellent": "LIKE_NEW", "refurbished": "LIKE_NEW",
    "renewed": "LIKE_NEW", "tested working": "LIKE_NEW",
    "good": "GOOD", "used - good": "GOOD", "minor wear": "GOOD",
    "light use": "GOOD", "gently used": "GOOD", "working": "GOOD",
    "fair": "FAIR", "used": "FAIR", "moderate wear": "FAIR",
    "acceptable": "FAIR", "functional": "FAIR",
    "salvage": "SALVAGE", "damaged": "SALVAGE", "for parts": "SALVAGE",
    "as-is": "SALVAGE", "broken": "SALVAGE", "not working": "SALVAGE",
    "defective": "SALVAGE",
}

BRAND_STRIP_SUFFIXES = [" inc", " llc", " corp", " co", " ltd", " corporation",
                         " incorporated", " company"]


# ── Main pipeline ──────────────────────────────────────────────────────

def create_ingestion_job(seller_id: str, file_path: str, file_name: str,
                          file_type: str) -> dict:
    """Create a new ingestion job and kick off the pipeline."""
    job_id = make_id("mfst_")
    ts = now_iso()
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    with get_db() as conn:
        conn.execute(
            """INSERT INTO ingestion_jobs
               (job_id, seller_id, file_key, file_name, file_type, file_size_bytes,
                status, status_history, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?)""",
            (job_id, seller_id, file_path, file_name, file_type, file_size,
             json_dumps([{"status": "QUEUED", "at": ts}]), ts),
        )

    log_event("ingestion", job_id, "IngestionJobCreated", "seller", seller_id,
              new_state={"file_name": file_name, "file_type": file_type},
              service="ingestion-service")

    return get_job(job_id)


def run_pipeline(job_id: str) -> dict:
    """Execute the full ingestion pipeline for a job.
    Steps: parse → extract → normalize → match → score."""
    job = get_job(job_id)
    if not job:
        return {"error": "JOB_NOT_FOUND"}

    ts = now_iso()
    _update_job_status(job_id, "PROCESSING", ts)

    try:
        # Step 1: Parse file into raw rows
        raw_rows, column_map, confidence = parse_manifest(
            job["file_key"], job["file_type"]
        )

        # Step 2: Create raw line items
        raw_item_ids = _store_raw_items(job_id, raw_rows, column_map, confidence)

        extraction_stats = {
            "total_rows": len(raw_rows),
            "columns_detected": list(column_map.keys()),
            "column_confidence": confidence,
        }
        _update_job_status(job_id, "EXTRACTED", ts, extraction_stats=extraction_stats)

        # Step 3: Normalize + match to canonical products
        norm_stats = normalize_items(job_id, raw_item_ids)

        _update_job_status(job_id, "NORMALIZED", ts, normalization_stats=norm_stats)

        # Step 4: Mark complete
        _update_job_status(job_id, "COMPLETED", ts)

    except Exception as e:
        _update_job_status(job_id, "FAILED", ts, error=str(e))
        return {"error": "PIPELINE_FAILED", "message": str(e)}

    log_event("ingestion", job_id, "IngestionPipelineCompleted", "system", "system",
              new_state={"rows": len(raw_rows), "match_rate": norm_stats.get("match_rate_pct", 0)},
              service="ingestion-service")

    return get_job(job_id)


# ── File parsing ───────────────────────────────────────────────────────

def parse_manifest(file_path: str, file_type: str) -> tuple:
    """Parse a manifest file, detect columns, return (rows, column_map, confidence).
    Returns:
        raw_rows: list of dicts with mapped field names
        column_map: {our_field: original_column_name}
        confidence: {our_field: 0.0-1.0}
    """
    if file_type in ("xlsx", "xls"):
        df = pd.read_excel(file_path, engine="openpyxl")
    elif file_type == "csv":
        df = pd.read_csv(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Clean up headers
    df.columns = [str(c).strip() for c in df.columns]

    # Detect column mapping
    column_map, confidence = _detect_columns(df.columns.tolist())

    # Extract rows using mapped columns
    raw_rows = []
    for _, row in df.iterrows():
        item = {}
        for our_field, orig_col in column_map.items():
            val = row.get(orig_col)
            if pd.notna(val):
                item[our_field] = str(val).strip() if not isinstance(val, (int, float)) else val
            else:
                item[our_field] = None
        raw_rows.append(item)

    return raw_rows, column_map, confidence


def _detect_columns(headers: list) -> tuple:
    """Map spreadsheet headers to our schema fields using regex heuristics."""
    column_map = {}
    confidence = {}
    used_headers = set()

    # First pass: exact/high-confidence matches
    for field in FIELD_PRIORITY:
        patterns = COLUMN_PATTERNS.get(field, [])
        best_match = None
        best_score = 0

        for header in headers:
            if header in used_headers:
                continue
            h_lower = header.lower().strip()
            for pattern in patterns:
                if re.search(pattern, h_lower):
                    # Score based on how specific the match is
                    score = len(pattern) / max(len(h_lower), 1)
                    score = min(score * 1.5, 1.0)
                    if score > best_score:
                        best_score = score
                        best_match = header

        if best_match:
            column_map[field] = best_match
            confidence[field] = round(min(best_score + 0.3, 1.0), 2)
            used_headers.add(best_match)

    # If we found "cost" but not "unit_cost", promote it
    if "cost" in column_map and "unit_cost" not in column_map:
        column_map["unit_cost"] = column_map.pop("cost")
        confidence["unit_cost"] = confidence.pop("cost", 0.6)

    # Remove the generic "cost" key if unit_cost was already found
    column_map.pop("cost", None)
    confidence.pop("cost", None)

    return column_map, confidence


# ── Raw item storage ───────────────────────────────────────────────────

def _store_raw_items(job_id: str, raw_rows: list, column_map: dict,
                      col_confidence: dict) -> list:
    """Store parsed rows as raw_line_items."""
    ts = now_iso()
    raw_item_ids = []

    with get_db() as conn:
        for i, row in enumerate(raw_rows):
            raw_id = make_id("rli_")
            raw_item_ids.append(raw_id)

            # Per-field confidence based on column detection + value presence
            field_conf = {}
            for field, conf in col_confidence.items():
                if row.get(field) is not None:
                    field_conf[field] = conf
                else:
                    field_conf[field] = 0.0

            conn.execute(
                """INSERT INTO raw_line_items
                   (raw_item_id, job_id, row_number, raw_fields,
                    extraction_confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (raw_id, job_id, i + 1, json_dumps(row),
                 json_dumps(field_conf), ts),
            )

    return raw_item_ids


# ── Normalization + product matching ───────────────────────────────────

def normalize_items(job_id: str, raw_item_ids: list) -> dict:
    """Normalize raw items: match products, grade conditions, clean brands."""
    ts = now_iso()

    # Load canonical products for matching
    with get_db() as conn:
        product_rows = conn.execute("SELECT * FROM canonical_products").fetchall()
    products = rows_to_dicts(product_rows)

    # Build lookup indexes
    asin_idx = {p["asin"]: p for p in products if p.get("asin")}
    upc_idx = {p["upc"]: p for p in products if p.get("upc")}

    stats = {"total": 0, "exact_match": 0, "high_match": 0,
             "low_match": 0, "unmatched": 0, "avg_confidence": 0}
    total_conf = 0

    with get_db() as conn:
        for raw_id in raw_item_ids:
            raw_row = conn.execute(
                "SELECT * FROM raw_line_items WHERE raw_item_id = ?", (raw_id,)
            ).fetchone()
            raw = dict_from_row(raw_row)
            fields = raw.get("raw_fields", {})
            if isinstance(fields, str):
                fields = json.loads(fields)

            stats["total"] += 1

            # Match to canonical product
            product, match_type, match_conf, matched_on = _match_product(
                fields, asin_idx, upc_idx, products
            )

            # Normalize condition
            raw_condition = str(fields.get("condition", "")).strip()
            condition_grade = _normalize_condition(raw_condition)

            # Normalize brand
            raw_brand = str(fields.get("brand", "")).strip() if fields.get("brand") else None
            brand_normalized = _normalize_brand(raw_brand, product)

            # Parse numeric fields
            quantity = _parse_int(fields.get("quantity"), default=1)
            unit_cost = _parse_cents(fields.get("unit_cost"))
            retail_price = _parse_cents(fields.get("retail"))

            # Fall back to product data if we have a match
            if product:
                if not retail_price and product.get("retail_price_cents"):
                    retail_price = product["retail_price_cents"]
                if not brand_normalized:
                    brand_normalized = product.get("brand_normalized")

            total_cost = unit_cost * quantity if unit_cost else 0
            title = fields.get("title") or (product["title"] if product else None)
            category_l1 = fields.get("category") or (product.get("category_l1") if product else None)

            # Overall row confidence
            row_conf = match_conf * 0.5 + (0.3 if condition_grade else 0) + (0.2 if quantity > 0 else 0)
            total_conf += row_conf

            # Track match stats
            if match_type == "EXACT":
                stats["exact_match"] += 1
            elif match_type == "HIGH":
                stats["high_match"] += 1
            elif match_type == "LOW":
                stats["low_match"] += 1
            else:
                stats["unmatched"] += 1

            nli_id = make_id("nli_")
            conn.execute(
                """INSERT INTO normalized_line_items
                   (normalized_item_id, raw_item_id, job_id, product_id,
                    match_type, match_confidence, matched_on,
                    title, brand_normalized, category_l1,
                    condition_raw, condition_grade, quantity,
                    unit_cost_cents, total_cost_cents,
                    retail_price_cents, resale_estimates,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)""",
                (
                    nli_id, raw_id, job_id,
                    product["product_id"] if product else None,
                    match_type, round(match_conf, 3), matched_on,
                    title, brand_normalized, category_l1,
                    raw_condition, condition_grade or "GOOD",
                    quantity, unit_cost or 0, total_cost,
                    retail_price, ts, ts,
                ),
            )

    matched = stats["exact_match"] + stats["high_match"]
    stats["match_rate_pct"] = round((matched / max(stats["total"], 1)) * 100, 1)
    stats["avg_confidence"] = round(total_conf / max(stats["total"], 1), 3)

    return stats


def _match_product(fields: dict, asin_idx: dict, upc_idx: dict,
                    all_products: list) -> tuple:
    """Try to match a raw item to a canonical product.
    Returns (product, match_type, confidence, matched_on)."""
    # Exact ASIN match
    asin = fields.get("asin")
    if asin is not None:
        asin = str(asin).strip().upper()
        if asin and asin != "NAN" and asin in asin_idx:
            return asin_idx[asin], "EXACT", 0.98, "asin"

    # Exact UPC match
    upc = fields.get("upc")
    if upc is not None:
        upc = str(upc).strip().split(".")[0]  # strip .0 from pandas float
        if upc and upc != "NAN" and upc in upc_idx:
            return upc_idx[upc], "EXACT", 0.97, "upc"

    # Fuzzy title match
    title = str(fields.get("title") or "").strip().lower()
    if title and len(title) > 5:
        best_product = None
        best_score = 0
        for p in all_products:
            p_title = (p.get("title") or "").lower()
            score = SequenceMatcher(None, title, p_title).ratio()
            if score > best_score:
                best_score = score
                best_product = p

        if best_score >= 0.65:
            return best_product, "HIGH", round(best_score, 3), "fuzzy_title"
        elif best_score >= 0.45:
            return best_product, "LOW", round(best_score, 3), "fuzzy_title"

    return None, "UNMATCHED", 0.0, None


def _normalize_condition(raw: str) -> str:
    """Map free-text condition to our enum."""
    if not raw:
        return None
    raw_lower = raw.lower().strip()

    # Direct lookup
    if raw_lower in CONDITION_MAP:
        return CONDITION_MAP[raw_lower]

    # Substring matching
    for phrase, grade in CONDITION_MAP.items():
        if phrase in raw_lower:
            return grade

    return None


def _normalize_brand(raw_brand: str, product: dict = None) -> str:
    """Normalize a brand name: strip suffixes, title-case, reconcile with product."""
    if not raw_brand:
        return product.get("brand_normalized") if product else None

    brand = raw_brand.strip()

    # Strip corporate suffixes
    brand_lower = brand.lower()
    for suffix in BRAND_STRIP_SUFFIXES:
        if brand_lower.endswith(suffix):
            brand = brand[:len(brand) - len(suffix)].strip()
            break

    # Title-case
    brand = brand.title()

    # If we have a product match, prefer its normalized brand
    if product and product.get("brand_normalized"):
        product_brand = product["brand_normalized"]
        # If they're close enough, use the canonical one
        ratio = SequenceMatcher(None, brand.lower(), product_brand.lower()).ratio()
        if ratio > 0.7:
            return product_brand

    return brand


def _parse_int(val, default=0) -> int:
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _parse_cents(val) -> int:
    """Parse a dollar value to cents. Handles $12.99, 12.99, 1299."""
    if val is None:
        return 0
    try:
        s = str(val).replace("$", "").replace(",", "").strip()
        f = float(s)
        # If the value looks like it's already in cents (> 1000 and no decimal)
        if f > 500 and "." not in s:
            return int(f)
        return int(round(f * 100))
    except (ValueError, TypeError):
        return 0


# ── Lot creation from job ──────────────────────────────────────────────

def create_lot_from_job(job_id: str, seller_id: str, overrides: dict = None) -> dict:
    """Create a lot + line items from a completed ingestion job."""
    from app.services.lots import create_lot, activate_lot
    from app.services.pricing import generate_pricing_recommendation

    overrides = overrides or {}

    job = get_job(job_id)
    if not job:
        return {"error": "JOB_NOT_FOUND"}
    if job["status"] != "COMPLETED":
        return {"error": "JOB_NOT_COMPLETED", "message": f"Job status is {job['status']}"}
    if job["seller_id"] != seller_id:
        return {"error": "NOT_AUTHORIZED"}

    # Get normalized items
    with get_db() as conn:
        nli_rows = conn.execute(
            "SELECT * FROM normalized_line_items WHERE job_id = ? ORDER BY created_at",
            (job_id,)
        ).fetchall()
    items = rows_to_dicts(nli_rows)

    if not items:
        return {"error": "NO_ITEMS", "message": "No normalized items found for this job."}

    # Compute lot summary stats
    total_units = sum(i.get("quantity", 0) for i in items)
    total_skus = len(items)
    total_cost = sum(i.get("total_cost_cents", 0) for i in items)
    total_retail = sum((i.get("retail_price_cents", 0) or 0) * i.get("quantity", 1) for i in items)

    # Condition distribution
    cond_counts = {}
    for i in items:
        g = i.get("condition_grade", "GOOD")
        cond_counts[g] = cond_counts.get(g, 0) + i.get("quantity", 1)
    cond_dist = {k: round(v / max(total_units, 1), 2) for k, v in cond_counts.items()}
    primary_cond = max(cond_counts, key=cond_counts.get) if cond_counts else "GOOD"

    # Top brands
    brand_counts = {}
    for i in items:
        b = i.get("brand_normalized")
        if b:
            brand_counts[b] = brand_counts.get(b, 0) + i.get("quantity", 1)
    top_brands = sorted(brand_counts, key=brand_counts.get, reverse=True)[:5]

    # Primary category
    cat_counts = {}
    for i in items:
        c = i.get("category_l1")
        if c:
            cat_counts[c] = cat_counts.get(c, 0) + 1
    primary_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "general"

    # Estimate pallets and weight
    pallet_count = max(1, total_units // 60)
    est_weight = total_units * 3  # rough: 3 lb/unit

    lot_data = {
        "title": overrides.get("title",
            f"{primary_cat.replace('_', ' ').title()} — {total_units} units, {pallet_count} pallet{'s' if pallet_count > 1 else ''}"),
        "description": overrides.get("description",
            f"Auto-generated from manifest {job['file_name']}. "
            f"{total_skus} SKUs, {total_units} units. "
            f"Top brands: {', '.join(top_brands[:3])}. "
            f"Condition: {primary_cond}."),
        "total_units": total_units,
        "total_skus": total_skus,
        "total_weight_lb": est_weight,
        "total_cube_cuft": pallet_count * 48,
        "pallet_count": pallet_count,
        "packing_type": "pallet",
        "estimated_retail_value_cents": total_retail,
        "total_cost_cents": total_cost,
        "condition_distribution": cond_dist,
        "condition_primary": primary_cond,
        "category_primary": primary_cat,
        "top_brands": top_brands,
        "ship_from_zip": overrides.get("ship_from_zip", "00000"),
        "ship_from_state": overrides.get("ship_from_state"),
        "ship_from_city": overrides.get("ship_from_city"),
    }

    lot = create_lot(seller_id, lot_data)
    lot_id = lot["lot_id"]
    ts = now_iso()

    # Create lot line items from normalized items
    with get_db() as conn:
        for idx, item in enumerate(items):
            lli_id = make_id("lli_")
            conn.execute(
                """INSERT INTO lot_line_items
                   (lot_line_item_id, lot_id, normalized_item_id, product_id,
                    quantity, condition_grade, unit_cost_cents, retail_price_cents,
                    brand_normalized, category_l1, sort_order, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (lli_id, lot_id, item["normalized_item_id"], item.get("product_id"),
                 item.get("quantity", 1), item.get("condition_grade", "GOOD"),
                 item.get("unit_cost_cents", 0), item.get("retail_price_cents"),
                 item.get("brand_normalized"), item.get("category_l1"),
                 idx, ts),
            )

        # Link lot to job + update normalized items
        conn.execute(
            "UPDATE normalized_line_items SET lot_id = ? WHERE job_id = ?",
            (lot_id, job_id),
        )

        # Update job with created lot
        lot_ids = job.get("lot_ids_created", [])
        if isinstance(lot_ids, str):
            lot_ids = json.loads(lot_ids)
        lot_ids.append(lot_id)
        conn.execute(
            "UPDATE ingestion_jobs SET lot_ids_created = ?, completed_at = ? WHERE job_id = ?",
            (json_dumps(lot_ids), ts, job_id),
        )

    log_event("ingestion", job_id, "LotCreatedFromJob", "seller", seller_id,
              new_state={"lot_id": lot_id, "total_units": total_units,
                         "total_skus": total_skus},
              service="ingestion-service")

    return {
        "lot": lot,
        "stats": {
            "total_units": total_units,
            "total_skus": total_skus,
            "total_cost_cents": total_cost,
            "estimated_retail_cents": total_retail,
            "condition_distribution": cond_dist,
            "top_brands": top_brands,
        },
    }


# ── Job helpers ────────────────────────────────────────────────────────

def get_job(job_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict_from_row(row) if row else None


def get_job_items(job_id: str) -> list:
    """Get normalized line items for a job with their raw data."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT n.*, r.raw_fields, r.extraction_confidence
               FROM normalized_line_items n
               JOIN raw_line_items r ON r.raw_item_id = n.raw_item_id
               WHERE n.job_id = ?
               ORDER BY r.row_number""",
            (job_id,)
        ).fetchall()
    return rows_to_dicts(rows)


def list_jobs(seller_id: str = None, limit: int = 50) -> list:
    with get_db() as conn:
        if seller_id:
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE seller_id = ? ORDER BY created_at DESC LIMIT ?",
                (seller_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ingestion_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return rows_to_dicts(rows)


def _update_job_status(job_id: str, status: str, ts: str,
                        extraction_stats: dict = None,
                        normalization_stats: dict = None,
                        error: str = None):
    """Update job status and optional stats."""
    with get_db() as conn:
        job_row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)).fetchone()
        job = dict_from_row(job_row)

        history = job.get("status_history", [])
        if isinstance(history, str):
            history = json.loads(history)
        entry = {"status": status, "at": ts}
        if error:
            entry["error"] = error
        history.append(entry)

        updates = {"status": status, "status_history": json_dumps(history)}
        if extraction_stats:
            updates["extraction_stats"] = json_dumps(extraction_stats)
        if normalization_stats:
            updates["normalization_stats"] = json_dumps(normalization_stats)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE ingestion_jobs SET {set_clause} WHERE job_id = ?",
            (*updates.values(), job_id),
        )
