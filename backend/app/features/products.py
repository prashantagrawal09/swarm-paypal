"""Human wording for products: "321 L milk", "112 trays of eggs", "S$1.92/L milk"."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Wording:
    name: str
    unit: str
    units: str
    joiner: str = " of "


WORDING = {
    "milk-full-cream-1l": Wording("milk", "L", "L", " "),
    "eggs-tray-30": Wording("eggs", "tray", "trays"),
    "butter-250g": Wording("butter", "block", "blocks"),
    "coffee-beans-1kg": Wording("coffee beans", "kg", "kg", " "),
    "cooking-oil-2l": Wording("cooking oil", "bottle", "bottles"),
    "paper-cups-12oz-50": Wording("12oz cups", "sleeve", "sleeves"),
    "lids-50": Wording("lids", "sleeve", "sleeves"),
    "takeaway-box-50": Wording("takeaway boxes", "pack", "packs"),
    "napkins-100": Wording("napkins", "pack", "packs"),
    "tomatoes-1kg": Wording("tomatoes", "kg", "kg", " "),
    "lettuce-1kg": Wording("lettuce", "kg", "kg", " "),
}


def wording(product: str) -> Wording:
    return WORDING.get(product, Wording(product, "unit", "units"))


# The words an owner might use for a unit, by the unit a product is counted in.
UNIT_WORDS = {
    "L": {"l", "litre", "litres", "liter", "liters", "ltr"},
    "kg": {"kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"},
    "tray": {"tray", "trays"},
    "block": {"block", "blocks"},
    "bottle": {"bottle", "bottles"},
    "sleeve": {"sleeve", "sleeves"},
    "pack": {"pack", "packs", "packet", "packets"},
}
# Every unit word Swarm knows, plus containers no product is counted in.
ANY_UNIT = set().union(*UNIT_WORDS.values()) | {
    "crate",
    "crates",
    "case",
    "cases",
    "carton",
    "cartons",
    "bag",
    "bags",
    "box",
    "boxes",
    "dozen",
    "tub",
    "tubs",
    "tin",
    "tins",
    "can",
    "cans",
    "jar",
    "jars",
    "sack",
    "sacks",
}


def counted_in(product: str, word: str) -> bool:
    """Whether `word` ("litres", "trays") is a unit this product is counted in."""
    return word.lower() in UNIT_WORDS.get(wording(product).unit, {wording(product).unit.lower()})


def describe(product: str, qty: int) -> str:
    w = wording(product)
    return f"{qty} {w.unit if qty == 1 else w.units}{w.joiner}{w.name}"


def describe_all(quantities: dict[str, int]) -> str:
    parts = [describe(product, qty) for product, qty in quantities.items() if qty]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def per_unit(product: str) -> str:
    w = wording(product)
    return f"/{w.unit} {w.name}"


def names(products: list[str]) -> str:
    parts = [wording(p).name for p in products]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " or " + parts[-1]
