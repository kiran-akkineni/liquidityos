"""
Invoice service — generate buyer and seller invoices on escrow funding.
"""

from app.db import get_db, dict_from_row, rows_to_dicts
from app.utils.helpers import make_id, now_iso, json_dumps, PLATFORM_FEE_PCT
from app.services.audit import log_event


def generate_invoices(order: dict) -> dict:
    """Generate buyer invoice and seller remittance for a funded order."""
    buyer_inv = _create_buyer_invoice(order)
    seller_inv = _create_seller_invoice(order)

    # Link first invoice to order
    ts = now_iso()
    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET invoice_id = ?, updated_at = ? WHERE order_id = ?",
            (buyer_inv["invoice_id"], ts, order["order_id"]),
        )

    return {"buyer_invoice": buyer_inv, "seller_invoice": seller_inv}


def _create_buyer_invoice(order: dict) -> dict:
    """Buyer invoice: lot price + platform fee + freight + insurance."""
    invoice_id = make_id("inv_")
    ts = now_iso()

    line_items = [
        {"description": "Lot purchase", "amount_cents": order["lot_price_cents"]},
        {"description": f"Platform fee ({PLATFORM_FEE_PCT*100:.0f}%)", "amount_cents": order["platform_fee_cents"]},
        {"description": "Freight", "amount_cents": order["freight_cost_cents"]},
        {"description": "Cargo insurance", "amount_cents": order["insurance_cents"]},
    ]
    subtotal = order["total_buyer_cost_cents"]

    with get_db() as conn:
        conn.execute(
            """INSERT INTO invoices
               (invoice_id, order_id, buyer_id, seller_id, invoice_type,
                line_items, subtotal_cents, tax_cents, total_cents,
                tax_exempt, created_at)
               VALUES (?, ?, ?, ?, 'buyer', ?, ?, 0, ?, 1, ?)""",
            (
                invoice_id, order["order_id"], order["buyer_id"], order["seller_id"],
                json_dumps(line_items), subtotal, subtotal, ts,
            ),
        )

    log_event("invoice", invoice_id, "InvoiceGenerated", "system", "system",
              new_state={"type": "buyer", "order_id": order["order_id"],
                         "total_cents": subtotal},
              service="invoice-service")

    return get_invoice(invoice_id)


def _create_seller_invoice(order: dict) -> dict:
    """Seller remittance: lot price minus platform fee."""
    invoice_id = make_id("inv_")
    ts = now_iso()

    line_items = [
        {"description": "Lot sale proceeds", "amount_cents": order["lot_price_cents"]},
        {"description": f"Platform fee ({PLATFORM_FEE_PCT*100:.0f}%)", "amount_cents": -order["platform_fee_cents"]},
    ]
    total = order["seller_payout_cents"]

    with get_db() as conn:
        conn.execute(
            """INSERT INTO invoices
               (invoice_id, order_id, buyer_id, seller_id, invoice_type,
                line_items, subtotal_cents, tax_cents, total_cents,
                tax_exempt, created_at)
               VALUES (?, ?, ?, ?, 'seller', ?, ?, 0, ?, 1, ?)""",
            (
                invoice_id, order["order_id"], order["buyer_id"], order["seller_id"],
                json_dumps(line_items), order["lot_price_cents"], total, ts,
            ),
        )

    log_event("invoice", invoice_id, "InvoiceGenerated", "system", "system",
              new_state={"type": "seller", "order_id": order["order_id"],
                         "total_cents": total},
              service="invoice-service")

    return get_invoice(invoice_id)


def get_invoice(invoice_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone()
    return dict_from_row(row) if row else None


def get_invoices_by_order(order_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM invoices WHERE order_id = ? ORDER BY created_at", (order_id,)
        ).fetchall()
    return rows_to_dicts(rows)
