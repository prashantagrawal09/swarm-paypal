"""The PayPal setup helper: `.env` edits, the report, and the question-by-question wizard."""

from __future__ import annotations

import stat

import pytest

from app.paypal.credentials import PayPalCredentials
from app.paypal.envfile import (
    adopt_smoke_vault,
    ensure_env,
    read_env,
    update_env_text,
    write_env,
)
from scripts import paypal_setup
from scripts.paypal_setup import AppCheck, Wizard, build_report

ALL_ON = frozenset(
    {
        "https://uri.paypal.com/services/invoicing",
        "https://uri.paypal.com/payments/payouts",
        "https://uri.paypal.com/services/vault/payment-tokens/readwrite",
    }
)

EXAMPLE = """\
# Swarm configuration.
SECRET_KEY=
PAYPAL_ENV=sandbox
# The platform account
PAYPAL_PLATFORM_CLIENT_ID=
PAYPAL_PLATFORM_CLIENT_SECRET=
PAYPAL_PLATFORM_EMAIL=
PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_ID=
PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET=
PAYPAL_SUPPLIER_FRESHDAIRY_EMAIL=
REAL_SHOP_CODES=cafe-mei,bakery-lim,kopi-corner,brew-lab
PAYPAL_SHOP_CAFE_MEI_EMAIL=
PAYPAL_SHOP_CAFE_MEI_VAULT_ID=
"""


async def accept(_: PayPalCredentials) -> AppCheck:
    return AppCheck(True, scopes=ALL_ON)


def answers(*replies: str):
    """A stand-in for input(): hands out the replies in order and records the prompts."""
    queue = list(replies)
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        assert queue, f"the wizard asked more than expected: {prompt!r}"
        return queue.pop(0)

    ask.prompts = prompts  # type: ignore[attr-defined]
    ask.left = queue  # type: ignore[attr-defined]
    return ask


@pytest.fixture
def env(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE)
    path = tmp_path / ".env"
    ensure_env(path, example)
    return path


# -- the .env file ---------------------------------------------------------------------------


def test_update_keeps_comments_and_order_and_appends_new_keys():
    text = "# top\nA=1\n\n# about b\nB=\nexport C=old\n"
    updated = update_env_text(text, {"B": "two", "C": "new", "D": "4"})
    assert updated == "# top\nA=1\n\n# about b\nB=two\nC=new\n\nD=4\n"


def test_values_that_need_quotes_survive_a_round_trip(tmp_path):
    path = tmp_path / ".env"
    path.write_text("A=\n")
    write_env(path, {"A": 'has space # and "quotes"', "B": "plain-Value_123"})
    assert read_env(path) == {"A": 'has space # and "quotes"', "B": "plain-Value_123"}


def test_ensure_env_creates_a_private_file_with_a_secret_key(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE)
    path = tmp_path / ".env"

    assert ensure_env(path, example) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    first = read_env(path)["SECRET_KEY"]
    assert len(first) >= 32
    assert "# The platform account" in path.read_text()

    # A second run changes nothing.
    assert ensure_env(path, example) is False
    assert read_env(path)["SECRET_KEY"] == first


def test_smoke_vault_goes_to_the_shop_whose_owner_approved(env):
    write_env(env, {"PAYPAL_SHOP_CAFE_MEI_EMAIL": "sb-mei@personal.example.com"})
    state = {"vault_id": "8kk845-vault", "payer_email": "SB-Mei@personal.example.com"}

    assert adopt_smoke_vault(state, env) == "cafe-mei"
    assert read_env(env)["PAYPAL_SHOP_CAFE_MEI_VAULT_ID"] == "8kk845-vault"
    # Already saved: left alone, even if the smoke test later approves a different wallet.
    assert adopt_smoke_vault({**state, "vault_id": "other"}, env) is None
    assert read_env(env)["PAYPAL_SHOP_CAFE_MEI_VAULT_ID"] == "8kk845-vault"


def test_smoke_vault_is_not_given_to_a_stranger(env):
    write_env(env, {"PAYPAL_SHOP_CAFE_MEI_EMAIL": "sb-mei@personal.example.com"})
    state = {"vault_id": "v-1", "payer_email": "sb-someone-else@personal.example.com"}
    assert adopt_smoke_vault(state, env) is None
    assert "PAYPAL_SHOP_CAFE_MEI_VAULT_ID" not in read_env(env)


# -- the report ------------------------------------------------------------------------------


async def test_report_for_an_empty_env_says_what_to_add():
    report = await build_report({}, check=accept)
    text = "\n".join(report.lines)
    assert not report.ready_for_smoke
    assert "Swarm Platform" in text and "not set up" in text
    assert any("Swarm Platform app's Client ID" in step for step in report.next_steps)
    assert any("FreshDairy SG app's Client ID" in step for step in report.next_steps)
    # Optional suppliers are not nagged about.
    assert not any("PackPro" in step for step in report.next_steps)


async def test_report_when_everything_needed_is_set():
    values = {
        "PAYPAL_PLATFORM_CLIENT_ID": "id-p",
        "PAYPAL_PLATFORM_CLIENT_SECRET": "s-p",
        "PAYPAL_PLATFORM_EMAIL": "sb-p@business.example.com",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_ID": "id-f",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET": "s-f",
        "PAYPAL_SUPPLIER_FRESHDAIRY_EMAIL": "sb-f@business.example.com",
        "PAYPAL_SHOP_CAFE_MEI_EMAIL": "sb-mei@personal.example.com",
        "REAL_SHOP_CODES": "cafe-mei",
    }
    report = await build_report(values, check=accept)
    text = "\n".join(report.lines)
    assert report.ready_for_smoke
    assert "keys work  ·  Vault on  Payouts on  Invoicing on" in text
    assert "PayPal not connected yet" in text
    assert report.next_steps == ["Run `make smoke` and approve in the browser when it asks."]
    assert "s-p" not in text and "id-p" not in text  # keys are never printed


async def test_report_flags_bad_keys_and_features_that_look_off():
    async def check(credentials: PayPalCredentials) -> AppCheck:
        if credentials.client_id == "id-f":
            return AppCheck(False, "PayPal rejected these keys.")
        return AppCheck(True, scopes=frozenset({"https://uri.paypal.com/services/invoicing"}))

    values = {
        "PAYPAL_PLATFORM_CLIENT_ID": "id-p",
        "PAYPAL_PLATFORM_CLIENT_SECRET": "s-p",
        "PAYPAL_PLATFORM_EMAIL": "sb-p@business.example.com",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_ID": "id-f",
        "PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET": "s-f",
    }
    report = await build_report(values, check=check)
    text = "\n".join(report.lines)
    assert not report.ready_for_smoke
    assert "KEYS DON'T WORK" in text
    assert "Vault unconfirmed  Payouts unconfirmed  Invoicing on" in text
    steps = " ".join(report.next_steps)
    assert "Couldn't confirm Payouts for the Swarm Platform app" in steps
    assert "Couldn't confirm Vault for the Swarm Platform app" in steps


# -- the wizard ------------------------------------------------------------------------------


async def test_wizard_minimum_path_writes_keys_and_limits_real_shops(env):
    ask = answers(
        "  AbCdEfGh-platform-id  ",  # pasted with spaces
        "sb-platform@business.example.com",
        "AbCdEfGh-dairy-id",
        "sb-dairy@business.example.com",
        "sb-mei@personal.example.com",
        "",  # "Add those now?" -> no
    )
    secret = answers("platform-secret", "dairy-secret")
    printed: list[str] = []

    report = await Wizard(env, ask=ask, ask_secret=secret, out=printed.append, check=accept).run()

    values = read_env(env)
    assert values["PAYPAL_PLATFORM_CLIENT_ID"] == "AbCdEfGh-platform-id"
    assert values["PAYPAL_PLATFORM_CLIENT_SECRET"] == "platform-secret"
    assert values["PAYPAL_PLATFORM_EMAIL"] == "sb-platform@business.example.com"
    assert values["PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET"] == "dairy-secret"
    assert values["PAYPAL_SHOP_CAFE_MEI_EMAIL"] == "sb-mei@personal.example.com"
    # Only the shop with a buyer account uses real sandbox money.
    assert values["REAL_SHOP_CODES"] == "cafe-mei"
    assert report.ready_for_smoke
    assert not ask.left and not secret.left
    assert "platform-secret" not in "\n".join(printed)
    assert "# The platform account" in env.read_text()


async def test_wizard_retries_rejected_keys_and_bad_emails(env):
    calls: list[str] = []

    async def check(credentials: PayPalCredentials) -> AppCheck:
        calls.append(credentials.client_secret)
        if credentials.client_secret == "wrong":
            return AppCheck(False, "PayPal rejected these keys.")
        return AppCheck(True, scopes=ALL_ON)

    ask = answers(
        "platform-id",
        "",  # Try again? -> yes
        "",  # Client ID: nothing saved yet, so asked again
        "platform-id",
        "not-an-email",
        "sb-platform@business.example.com",
        "dairy-id",
        "sb-dairy@business.example.com",
        "sb-mei@personal.example.com",
        "n",
    )
    secret = answers("wrong", "", "right", "dairy-secret")
    printed: list[str] = []

    await Wizard(env, ask=ask, ask_secret=secret, out=printed.append, check=check).run()

    text = "\n".join(printed)
    assert "PayPal rejected these keys." in text
    assert "Both the Client ID and the Secret are needed." in text
    assert "doesn't look like an email" in text
    values = read_env(env)
    assert values["PAYPAL_PLATFORM_CLIENT_SECRET"] == "right"
    assert "wrong" not in env.read_text()  # rejected keys are never saved
    assert calls[:2] == ["wrong", "right"]


async def test_wizard_second_run_keeps_values_on_enter(env):
    first = answers(
        "platform-id",
        "sb-platform@business.example.com",
        "dairy-id",
        "sb-dairy@business.example.com",
        "sb-mei@personal.example.com",
        "",
    )
    await Wizard(
        env,
        ask=first,
        ask_secret=answers("platform-secret", "dairy-secret"),
        out=lambda _: None,
        check=accept,
    ).run()
    before = read_env(env)

    again = answers("", "", "", "", "", "")
    secret = answers("", "")
    await Wizard(env, ask=again, ask_secret=secret, out=lambda _: None, check=accept).run()

    assert read_env(env) == before
    assert "Enter keeps it" in again.prompts[0]
    assert "platform-id" not in again.prompts[0]  # short IDs are not echoed back
    assert "platform-secret" not in "".join(secret.prompts)


async def test_wizard_full_demo_adds_suppliers_and_shops_and_skips_blanks(env):
    ask = answers(
        "platform-id",
        "sb-platform@business.example.com",
        "dairy-id",
        "sb-dairy@business.example.com",
        "sb-mei@personal.example.com",
        "y",
        "packpro-id",
        "sb-pack@business.example.com",
        "",  # Johor Farm Fresh: skipped
        "sb-lim@personal.example.com",
        "",  # Kopi Corner: skipped
        "sb-brew@personal.example.com",
    )
    secret = answers("platform-secret", "dairy-secret", "packpro-secret")

    await Wizard(env, ask=ask, ask_secret=secret, out=lambda _: None, check=accept).run()

    values = read_env(env)
    assert values["PAYPAL_SUPPLIER_PACKPRO_CLIENT_ID"] == "packpro-id"
    assert "PAYPAL_SUPPLIER_JOHORFARM_CLIENT_ID" not in values
    assert values["REAL_SHOP_CODES"] == "cafe-mei,bakery-lim,brew-lab"
    assert not ask.left and not secret.left


def test_specs_match_the_seed_data_and_the_example_file():
    example = (paypal_setup.REPO_ROOT / ".env.example").read_text()
    for app in paypal_setup.app_specs():
        assert f"{app.prefix}_CLIENT_ID=" in example
    for shop in paypal_setup.shop_specs():
        assert f"{shop.email_key}=" in example
        assert f"{shop.vault_key}=" in example
    assert [a.name for a in paypal_setup.app_specs() if a.needed_for_smoke] == [
        "Swarm Platform",
        "FreshDairy SG",
    ]
