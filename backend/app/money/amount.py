"""Money as integer minor units plus an ISO-4217 currency code. Never floats.

`Money` is the only type that crosses into PayPal requests. It knows how to render itself
as PayPal's decimal string ("12.30") and how to parse one back, so no other module ever
does string or float arithmetic on amounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# PayPal currencies that have no minor unit (amounts must be whole numbers).
# https://developer.paypal.com/api/rest/reference/currency-codes/
ZERO_DECIMAL_CURRENCIES = frozenset({"HUF", "JPY", "TWD"})

CURRENCY_SYMBOLS = {"SGD": "S$", "USD": "US$", "MYR": "RM"}


def minor_unit_digits(currency: str) -> int:
    return 0 if currency in ZERO_DECIMAL_CURRENCIES else 2


@dataclass(frozen=True, order=False)
class Money:
    """An amount in minor units (cents for SGD). Immutable and currency-safe."""

    cents: int
    currency: str = "SGD"

    def __post_init__(self) -> None:
        if not isinstance(self.cents, int) or isinstance(self.cents, bool):
            raise TypeError(f"Money.cents must be an int, got {type(self.cents).__name__}")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"Invalid currency code: {self.currency!r}")

    # -- construction -----------------------------------------------------------------

    @classmethod
    def zero(cls, currency: str = "SGD") -> Money:
        return cls(0, currency)

    @classmethod
    def from_paypal(cls, value: str, currency: str) -> Money:
        """Parse PayPal's decimal string ("12.30") exactly, rejecting extra precision."""
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Not a decimal amount: {value!r}") from exc
        scaled = amount.scaleb(minor_unit_digits(currency))
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{value!r} has more precision than {currency} allows")
        return cls(int(scaled), currency)

    @classmethod
    def from_paypal_amount(cls, amount: dict[str, str]) -> Money:
        """Parse a PayPal money object: `{currency_code, value}` (or `{currency, value}`)."""
        currency = amount.get("currency_code") or amount.get("currency")
        if not currency:
            raise ValueError(f"Money object without a currency: {amount!r}")
        return cls.from_paypal(amount["value"], currency)

    # -- rendering --------------------------------------------------------------------

    def to_paypal_value(self) -> str:
        digits = minor_unit_digits(self.currency)
        if digits == 0:
            return str(self.cents)
        return f"{Decimal(self.cents).scaleb(-digits):.{digits}f}"

    def to_paypal(self) -> dict[str, str]:
        """PayPal Orders / Payments / Invoicing money object."""
        return {"currency_code": self.currency, "value": self.to_paypal_value()}

    def to_payouts(self) -> dict[str, str]:
        """Payouts v1 uses `currency`, not `currency_code`."""
        return {"currency": self.currency, "value": self.to_paypal_value()}

    def format(self) -> str:
        symbol = CURRENCY_SYMBOLS.get(self.currency, f"{self.currency} ")
        sign = "-" if self.cents < 0 else ""
        return f"{sign}{symbol}{Money(abs(self.cents), self.currency).to_paypal_value()}"

    def __str__(self) -> str:
        return self.format()

    # -- arithmetic -------------------------------------------------------------------

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Cannot combine Money with {type(other).__name__}")
        if other.currency != self.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.cents - other.cents, self.currency)

    def __mul__(self, quantity: int) -> Money:
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise TypeError("Money can only be multiplied by an int quantity")
        return Money(self.cents * quantity, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.cents, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.cents < other.cents

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.cents <= other.cents

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.cents > other.cents

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.cents >= other.cents

    @property
    def is_positive(self) -> bool:
        return self.cents > 0
