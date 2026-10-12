"""Which PayPal account is which, and the gateway object that talks to each one.

Credentials are looked up by env-var prefix (the database stores only the prefix, for
example `PAYPAL_SUPPLIER_FRESHDAIRY`); `GatewayRegistry` hands out one gateway per account
and decides, from the account's `paypal_mode`, whether that is the real sandbox client or
the simulator.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from app.clock import Clock, SystemClock
from app.config import Settings, env_value, get_settings
from app.paypal.client import LIVE_BASE_URL, PayPalClient
from app.paypal.credentials import PayPalCredentials
from app.paypal.errors import PayPalConfigError
from app.paypal.interface import PayPalGateway, PayPalMode
from app.paypal.simulated import SimulatedPayPalClient, SimulatedPayPalState

PLATFORM_PREFIX = "PAYPAL_PLATFORM"
PLATFORM_LABEL = "platform"


def credential_keys(prefix: str) -> tuple[str, str, str]:
    return f"{prefix}_CLIENT_ID", f"{prefix}_CLIENT_SECRET", f"{prefix}_EMAIL"


def missing_credential_keys(prefix: str) -> list[str]:
    client_id_key, secret_key, _ = credential_keys(prefix)
    return [key for key in (client_id_key, secret_key) if not env_value(key)]


def credentials_for_prefix(prefix: str, label: str | None = None) -> PayPalCredentials | None:
    """Credentials for an account, or None if its client ID / secret are not configured."""
    client_id_key, secret_key, email_key = credential_keys(prefix)
    client_id, secret = env_value(client_id_key), env_value(secret_key)
    if not client_id or not secret:
        return None
    return PayPalCredentials(
        client_id=client_id,
        client_secret=secret,
        email=env_value(email_key),
        label=label or prefix.removeprefix("PAYPAL_").lower(),
    )


def platform_credentials() -> PayPalCredentials | None:
    return credentials_for_prefix(PLATFORM_PREFIX, PLATFORM_LABEL)


def shop_email_key(shop_code: str) -> str:
    """`cafe-mei` -> `PAYPAL_SHOP_CAFE_MEI_EMAIL`."""
    return f"PAYPAL_SHOP_{shop_code.upper().replace('-', '_')}_EMAIL"


def shop_vault_key(shop_code: str) -> str:
    """`cafe-mei` -> `PAYPAL_SHOP_CAFE_MEI_VAULT_ID`."""
    return f"PAYPAL_SHOP_{shop_code.upper().replace('-', '_')}_VAULT_ID"


def shop_paypal_email(shop_code: str) -> str | None:
    return env_value(shop_email_key(shop_code))


class GatewayRegistry:
    """One gateway per account per process. Simulated accounts share one simulated PayPal."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        sim_state: SimulatedPayPalState | None = None,
        http: httpx.AsyncClient | None = None,
        sim_on_change: Callable[[SimulatedPayPalState], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.clock = clock or SystemClock()
        self.sim_state = sim_state or SimulatedPayPalState()
        self.sim_on_change = sim_on_change
        self._http = http
        self._gateways: dict[tuple[str, PayPalMode], PayPalGateway] = {}

    def gateway(self, prefix: str, mode: PayPalMode, label: str | None = None) -> PayPalGateway:
        label = label or prefix.removeprefix("PAYPAL_").lower()
        key = (label, mode)
        if key not in self._gateways:
            self._gateways[key] = self._build(prefix, mode, label)
        return self._gateways[key]

    def platform(self, mode: PayPalMode = "REAL") -> PayPalGateway:
        return self.gateway(PLATFORM_PREFIX, mode, PLATFORM_LABEL)

    def _build(self, prefix: str, mode: PayPalMode, label: str) -> PayPalGateway:
        if mode == "SIMULATED":
            return SimulatedPayPalClient(
                label,
                state=self.sim_state,
                clock=self.clock,
                approval_base_url=self.settings.public_backend_url,
                on_change=self.sim_on_change,
            )
        if self.settings.paypal_base_url == LIVE_BASE_URL:
            raise PayPalConfigError("PAYPAL_ENV=live is not supported", operation="registry")
        credentials = credentials_for_prefix(prefix, label)
        if credentials is None:
            missing = ", ".join(missing_credential_keys(prefix))
            raise PayPalConfigError(
                f"PayPal account {label!r} is REAL but {missing} is not set", operation="registry"
            )
        return PayPalClient(credentials, base_url=self.settings.paypal_base_url, http=self._http)

    def forget_gateways(self) -> None:
        """Drop cached simulated gateways so they pick up a fresh simulator state."""
        for key in [k for k in self._gateways if k[1] == "SIMULATED"]:
            del self._gateways[key]

    async def aclose(self) -> None:
        for gateway in self._gateways.values():
            await gateway.aclose()
        self._gateways.clear()


def get_platform_gateway() -> PayPalGateway:
    """FastAPI dependency: the platform's real sandbox gateway."""
    from app.runtime import get_runtime

    return get_runtime().registry.platform("REAL")
