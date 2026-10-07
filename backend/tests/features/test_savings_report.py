"""The weekly report's wording follows what actually happened."""

from __future__ import annotations

from datetime import date

from app.features.savings import ShopWeek, report_text


def test_surplus_sales_and_emergency_help_are_reported_separately():
    week = ShopWeek("little-pasta", "Little Pasta", date(2026, 10, 12))
    week.help_income_cents = 852
    text = report_text(week, 0)
    assert "Helping a neighbour in a pinch brought in S$8.52." in text
    assert "selling surplus" not in text and "kg of food" not in text

    week.swap_income_cents, week.food_saved_grams = 968, 8400
    text = report_text(week, 0)
    assert "You earned S$9.68 selling surplus (8.4 kg of food saved)." in text
