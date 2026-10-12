"""PayPal sandbox setup helper: puts your sandbox keys into `.env` and checks they work.

    python scripts/paypal_setup.py            # asks for each value, tests it, saves it
    python scripts/paypal_setup.py --check    # only reports what is set and whether it works

The only network call is to PayPal's sandbox token endpoint, to test each app's keys.
Secrets are typed with hidden input and written only to the git-ignored `.env` at the repo
root. Where to find each value: docs/paypal-setup.md.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import ENV_FILE, REPO_ROOT
from app.paypal.accounts import PLATFORM_PREFIX, credential_keys, shop_email_key, shop_vault_key
from app.paypal.client import SANDBOX_BASE_URL, PayPalClient
from app.paypal.credentials import PayPalCredentials
from app.paypal.envfile import ensure_env, read_env, write_env
from app.paypal.errors import PayPalAuthError, PayPalError

SEED_DIR = REPO_ROOT / "backend" / "app" / "seed" / "data"
SMOKE_STATE = REPO_ROOT / "backend" / "scripts" / ".smoke_state.json"

SMOKE_SUPPLIER_PREFIX = "PAYPAL_SUPPLIER_FRESHDAIRY"
# The shops that can use real sandbox money, in the order they are asked for.
REAL_SHOP_CHOICES = ("cafe-mei", "bakery-lim", "kopi-corner", "brew-lab")
SMOKE_SHOP = "cafe-mei"

# A feature that is switched on for an app shows up as a permission on its token. This is a
# hint for the setup report; `make smoke` is what proves each feature.
FEATURE_HINTS = {"Invoicing": "invoicing", "Payouts": "payouts", "Vault": "payment-tokens"}

Ask = Callable[[str], str]
Out = Callable[[str], None]


@dataclass(frozen=True)
class AppSpec:
    """One REST app in the Developer Dashboard (the platform's, or a supplier's)."""

    prefix: str
    name: str
    features: tuple[str, ...]
    needed_for_smoke: bool


@dataclass(frozen=True)
class ShopSpec:
    """One shop owner's sandbox personal (buyer) account."""

    code: str
    name: str
    needed_for_smoke: bool

    @property
    def email_key(self) -> str:
        return shop_email_key(self.code)

    @property
    def vault_key(self) -> str:
        return shop_vault_key(self.code)


@dataclass(frozen=True)
class AppCheck:
    ok: bool
    problem: str | None = None
    scopes: frozenset[str] = frozenset()

    def has(self, feature: str) -> bool:
        return any(FEATURE_HINTS[feature] in scope for scope in self.scopes)


CheckApp = Callable[[PayPalCredentials], Awaitable[AppCheck]]


def app_specs() -> list[AppSpec]:
    suppliers = json.loads((SEED_DIR / "suppliers.json").read_text())
    return [
        AppSpec(PLATFORM_PREFIX, "Swarm Platform", ("Vault", "Payouts", "Invoicing"), True),
        *(
            AppSpec(
                s["api_credentials_ref"],
                s["name"],
                ("Invoicing",),
                s["api_credentials_ref"] == SMOKE_SUPPLIER_PREFIX,
            )
            for s in suppliers
        ),
    ]


def shop_specs() -> list[ShopSpec]:
    names = {s["code"]: s["name"] for s in json.loads((SEED_DIR / "shops.json").read_text())}
    return [ShopSpec(code, names[code], code == SMOKE_SHOP) for code in REAL_SHOP_CHOICES]


# ---------------------------------------------------------------------------------------
# Checking an app's keys with PayPal
# ---------------------------------------------------------------------------------------


async def check_app(credentials: PayPalCredentials) -> AppCheck:
    """Ask the sandbox for a token with these keys. Nothing else is called."""
    client = PayPalClient(credentials, base_url=SANDBOX_BASE_URL, max_retries=1)
    try:
        await client.access_token()
    except PayPalAuthError:
        return AppCheck(
            False,
            "PayPal rejected these keys. Copy the Client ID and the Secret from the same app, "
            "with the dashboard switched to Sandbox (not Live).",
        )
    except PayPalError as exc:
        return AppCheck(False, f"Could not check with PayPal: {exc.message}")
    finally:
        await client.aclose()
    return AppCheck(True, scopes=client.token_scopes)


def credentials_in(values: Mapping[str, str], app: AppSpec) -> PayPalCredentials | None:
    id_key, secret_key, email_key = credential_keys(app.prefix)
    if not values.get(id_key) or not values.get(secret_key):
        return None
    return PayPalCredentials(
        client_id=values[id_key],
        client_secret=values[secret_key],
        email=values.get(email_key),
        label=app.name,
    )


def feature_line(app: AppSpec, check: AppCheck) -> str:
    return "  ".join(
        f"{feature} {'on' if check.has(feature) else 'unconfirmed'}" for feature in app.features
    )


def missing_features(app: AppSpec, check: AppCheck) -> list[str]:
    return [feature for feature in app.features if not check.has(feature)]


def unconfirmed(app: AppSpec, feature: str) -> str:
    return (
        f"Couldn't confirm {feature} for the {app.name} app from its token. Check it is "
        "ticked under Features in the dashboard and saved; `make smoke` proves it."
    )


# ---------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------


@dataclass
class Report:
    lines: list[str]
    ready_for_smoke: bool
    next_steps: list[str]


async def build_report(
    values: Mapping[str, str],
    *,
    check: CheckApp = check_app,
    smoke_state: Mapping[str, Any] | None = None,
) -> Report:
    apps, shops = app_specs(), shop_specs()
    width = max(len(name) for name in [*(a.name for a in apps), *(s.name for s in shops)])
    lines: list[str] = ["Apps (business accounts)"]
    next_steps: list[str] = []
    ready = True

    for app in apps:
        id_key, secret_key, email_key = credential_keys(app.prefix)
        credentials = credentials_in(values, app)
        if credentials is None:
            partly = bool(values.get(id_key) or values.get(secret_key))
            status = "Client ID or Secret missing" if partly else "not set up"
            if app.needed_for_smoke:
                ready = False
                next_steps.append(f"Add the {app.name} app's Client ID and Secret.")
            elif not partly:
                status += " (runs on the simulator)"
            lines.append(f"  {app.name:<{width}}  {status}")
            continue
        result = await check(credentials)
        if not result.ok:
            ready = ready and not app.needed_for_smoke
            lines.append(f"  {app.name:<{width}}  KEYS DON'T WORK: {result.problem}")
            next_steps.append(f"Fix the {app.name} keys ({id_key}, {secret_key}).")
            continue
        note = "" if values.get(email_key) else "  (account email missing)"
        lines.append(f"  {app.name:<{width}}  keys work  ·  {feature_line(app, result)}{note}")
        if not values.get(email_key):
            next_steps.append(f"Add {email_key} (the sandbox email of the {app.name} account).")
        for feature in missing_features(app, result):
            next_steps.append(unconfirmed(app, feature))

    lines += ["", "Shops (personal buyer accounts)"]
    real_codes = {c.strip() for c in values.get("REAL_SHOP_CODES", "").split(",") if c.strip()}
    saved_payer = (smoke_state or {}).get("payer_email")
    for shop in shops:
        email = values.get(shop.email_key)
        if not email:
            lines.append(f"  {shop.name:<{width}}  no buyer email (runs on the simulator)")
            if shop.needed_for_smoke:
                next_steps.append(
                    f"Add {shop.email_key}: the sandbox email of {shop.name}'s owner."
                )
            continue
        if values.get(shop.vault_key):
            wallet = "PayPal saved"
        elif saved_payer and saved_payer == email:
            wallet = "PayPal saved by the smoke test"
        else:
            wallet = "PayPal not connected yet"
        listed = "" if shop.code in real_codes else "  (not in REAL_SHOP_CODES)"
        lines.append(f"  {shop.name:<{width}}  buyer email set  ·  {wallet}{listed}")

    if ready and not next_steps:
        next_steps.append("Run `make smoke` and approve in the browser when it asks.")
    elif ready:
        next_steps.append("Then run `make smoke`.")
    return Report(lines, ready, next_steps)


def print_report(report: Report, out: Out) -> None:
    for line in report.lines:
        out(line)
    out("")
    out("Next")
    for step in report.next_steps:
        out(f"  - {step}")


# ---------------------------------------------------------------------------------------
# The wizard
# ---------------------------------------------------------------------------------------


def looks_like_email(value: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None


def mask(value: str) -> str:
    return f"{value[:4]}...{value[-4:]}" if len(value) > 12 else "set"


class Wizard:
    def __init__(
        self,
        path: Path,
        *,
        ask: Ask = input,
        ask_secret: Ask = getpass.getpass,
        out: Out = print,
        check: CheckApp = check_app,
    ) -> None:
        self.path = path
        self.ask = ask
        self.ask_secret = ask_secret
        self.out = out
        self.check = check

    def values(self) -> dict[str, str]:
        return read_env(self.path)

    def _value(self, label: str, current: str | None, *, secret: bool = False) -> str:
        """One answer. Enter keeps the current value; spaces around a paste are dropped."""
        if current:
            shown = "hidden" if secret else mask(current)
            prompt = f"  {label} [{shown}, Enter keeps it]: "
        else:
            prompt = f"  {label}{' (hidden as you paste)' if secret else ''}: "
        answer = (self.ask_secret if secret else self.ask)(prompt).strip()
        return answer or (current or "")

    def _email(self, label: str, current: str | None, *, optional: bool) -> str:
        while True:
            answer = self._value(label, current)
            if not answer and optional:
                return ""
            if looks_like_email(answer):
                return answer
            self.out("    That doesn't look like an email. Sandbox emails look like")
            self.out("    sb-abc123@business.example.com or sb-abc123@personal.example.com.")

    async def app(self, app: AppSpec, *, optional: bool) -> bool:
        """Ask for one app's keys and email, test the keys, save. False if it was skipped."""
        id_key, secret_key, email_key = credential_keys(app.prefix)
        while True:
            values = self.values()
            client_id = self._value("Client ID", values.get(id_key))
            if not client_id and optional:
                self.out("  Skipped. It runs on the simulator until you add it.")
                return False
            if looks_like_email(client_id):
                self.out("    That is an email. The Client ID is the long code on the app's page.")
                continue
            client_secret = self._value("Secret", values.get(secret_key), secret=True)
            if not client_id or not client_secret:
                self.out("    Both the Client ID and the Secret are needed.")
                continue
            if client_id == client_secret:
                self.out("    The Client ID and the Secret are the same; paste the Secret again.")
                continue
            credentials = PayPalCredentials(client_id, client_secret, label=app.name)
            self.out("  Checking with PayPal...")
            result = await self.check(credentials)
            if result.ok:
                write_env(self.path, {id_key: client_id, secret_key: client_secret})
                self.out(f"  PayPal accepted the keys.  {feature_line(app, result)}")
                for feature in missing_features(app, result):
                    self.out(f"    {unconfirmed(app, feature)}")
                break
            self.out(f"    {result.problem}")
            if self.ask("  Try again? [Y/n]: ").strip().lower().startswith("n"):
                return False
        email = self._email(
            "Sandbox email of this business account", self.values().get(email_key), optional=False
        )
        write_env(self.path, {email_key: email})
        return True

    def shop(self, shop: ShopSpec, *, optional: bool) -> bool:
        label = f"Sandbox email of {shop.name}'s owner (personal account)"
        email = self._email(label, self.values().get(shop.email_key), optional=optional)
        if not email:
            self.out("  Skipped. This shop runs on the simulator.")
            return False
        write_env(self.path, {shop.email_key: email})
        return True

    async def run(self) -> Report:
        out = self.out
        if ensure_env(self.path):
            out("Created .env from .env.example.")
        out("")
        out("Swarm: PayPal sandbox setup")
        out("Paste each value from developer.paypal.com (Sandbox). Where to find them:")
        out("docs/paypal-setup.md. Everything is saved to .env as you go, so you can stop")
        out("with Ctrl+C and carry on later.")

        apps, shops = app_specs(), shop_specs()
        needed_apps = [a for a in apps if a.needed_for_smoke]
        other_apps = [a for a in apps if not a.needed_for_smoke]
        first_shop = next(s for s in shops if s.needed_for_smoke)
        other_shops = [s for s in shops if not s.needed_for_smoke]
        total = len(needed_apps) + 1

        for number, app in enumerate(needed_apps, start=1):
            out("")
            out(f"{number} of {total}: {app.name}")
            out(f"  Apps & Credentials > {app.name} (features: {', '.join(app.features)})")
            await self.app(app, optional=False)

        out("")
        out(f"{total} of {total}: {first_shop.name}'s owner")
        out("  Testing Tools > Sandbox Accounts > the Personal account you made for this shop")
        self.shop(first_shop, optional=False)

        out("")
        out("That is enough for `make smoke`. The full demo uses two more suppliers and three")
        out("more shop owners; anything you skip runs on the simulator.")
        if self.ask("Add those now? [y/N]: ").strip().lower().startswith("y"):
            for app in other_apps:
                out("")
                out(f"{app.name} (Enter on Client ID skips it)")
                await self.app(app, optional=True)
            for shop in other_shops:
                out("")
                out(f"{shop.name} (Enter skips it)")
                self.shop(shop, optional=True)

        self._settle()
        out("")
        report = await build_report(self.values(), check=self.check, smoke_state=load_smoke())
        print_report(report, out)
        return report

    def _settle(self) -> None:
        """Make the REAL shops exactly the ones with a buyer account, and keep sandbox on."""
        values = self.values()
        real = [s.code for s in shop_specs() if values.get(s.email_key)]
        write_env(
            self.path,
            {"PAYPAL_ENV": "sandbox", "REAL_SHOP_CODES": ",".join(real)},
        )


def load_smoke(path: Path = SMOKE_STATE) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report only; ask nothing")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.check:
        if not ENV_FILE.exists():
            print("There is no .env yet. Run `make paypal-setup` to create it.")
            return 1
        values = {**read_env(ENV_FILE), **{k: v for k, v in os.environ.items() if v}}
        print("\nSwarm: PayPal sandbox setup\n")
        report = await build_report(values, smoke_state=load_smoke())
        print_report(report, print)
        return 0 if report.ready_for_smoke else 1
    try:
        report = await Wizard(ENV_FILE).run()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. What you entered is saved; run `make paypal-setup` to carry on.")
        return 130
    return 0 if report.ready_for_smoke else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
