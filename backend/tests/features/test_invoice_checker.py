"""The invoice check itself (pure function)."""

from __future__ import annotations

from app.features.invoice_checker import Expected, ExpectedLine, check

EXPECTED = Expected(
    {
        "milk-full-cream-1l": ExpectedLine("milk-full-cream-1l", "MILK", "Milk", 290, 205),
        "eggs-tray-30": ExpectedLine("eggs-tray-30", "EGGS", "Eggs", 100, 800),
    },
    delivery_cents=4500,
)


def line(product, qty, price):
    return {
        "product": product,
        "name": product,
        "qty": qty,
        "unit_price_cents": price,
        "total_cents": qty * price,
    }


def invoice(*lines, delivery=4500):
    rows = list(lines)
    if delivery is not None:
        rows.append(line("delivery", 1, delivery))
    return rows, sum(r["total_cents"] for r in rows)


def test_exact_invoice_is_approved():
    rows, total = invoice(line("milk-full-cream-1l", 290, 205), line("eggs-tray-30", 100, 800))
    report = check(EXPECTED, rows, total)
    assert report.approved and report.overcharge_cents == 0


def test_wrong_price_is_rejected_with_the_spec_wording():
    rows, total = invoice(line("milk-full-cream-1l", 290, 230), line("eggs-tray-30", 100, 800))
    report = check(EXPECTED, rows, total)
    assert not report.approved
    assert report.summary() == (
        "Milk: charged S$2.30/L, agreed S$2.05/L, 290 L, overcharge S$72.50."
    )
    assert report.overcharge_cents == 7250


def test_quantity_missing_line_and_delivery_mismatches():
    rows, total = invoice(line("milk-full-cream-1l", 300, 205), delivery=5000)
    report = check(EXPECTED, rows, total)
    kinds = {issue["kind"] for issue in report.issues}
    assert kinds == {"quantity", "missing_line", "delivery"}
    assert "billed 300, 290 delivered" in report.summary()


def test_unexpected_lines_are_flagged():
    rows, total = invoice(
        line("milk-full-cream-1l", 290, 205),
        line("eggs-tray-30", 100, 800),
        line("butter-250g", 5, 400),
    )
    assert {i["kind"] for i in check(EXPECTED, rows, total).issues} == {"unexpected_line"}
