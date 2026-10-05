"""PayPal REST app credentials for one account (platform or a supplier)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PayPalCredentials:
    client_id: str
    client_secret: str = field(repr=False)
    email: str | None = None
    label: str = "platform"

    def __post_init__(self) -> None:
        if not self.client_id or not self.client_secret:
            raise ValueError(f"PayPal credentials for {self.label!r} are incomplete")
