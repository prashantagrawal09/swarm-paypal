"""PayPal Agent Toolkit adapter: tool schemas, allow-list, and HTTP behaviour."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import requests

from app.money.amount import Money
from app.paypal.credentials import PayPalCredentials
from app.paypal.errors import PayPalUnprocessableError
from app.paypal.interface import InvoiceDraft, InvoiceLine
from app.paypal.toolkit import (
    SUPPLIER_INVOICE_TOOLS,
    AgentToolkit,
    draft_to_toolkit_params,
    toolkit_tool_names,
)

CREDS = PayPalCredentials(client_id="cid", client_secret="secret", label="freshdairy")


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code = status
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.request = type("Req", (), {"headers": {"Authorization": "Bearer abcdefghijkl"}})()

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)  # type: ignore[arg-type]


@pytest.fixture
def fake_http(monkeypatch):
    """Replace the toolkit's `requests` calls with canned responses."""
    import paypal_agent_toolkit.shared.paypal_client as toolkit_client

    calls: list[dict[str, Any]] = []
    responses: dict[tuple[str, str], FakeResponse] = {}

    def handler(method: str):
        def call(url: str, headers=None, json=None, data=None, auth=None, **_: Any):
            calls.append({"method": method, "url": url, "json": json})
            if url.endswith("/v1/oauth2/token"):
                return FakeResponse(200, {"access_token": "tok", "expires_in": 32400})
            path = url.split("paypal.com", 1)[1]
            return responses[(method, path)]

        return call

    monkeypatch.setattr(toolkit_client.requests, "post", handler("POST"))
    monkeypatch.setattr(toolkit_client.requests, "get", handler("GET"))
    return calls, responses


def _draft() -> InvoiceDraft:
    return InvoiceDraft(
        invoice_number="SW-GO1-FD-1",
        invoice_date=date(2026, 10, 8),
        currency="SGD",
        recipient_email="platform@example.com",
        recipient_business_name="Swarm",
        invoicer_business_name="FreshDairy SG",
        lines=[InvoiceLine("Milk 1L", Decimal(290), Money(205))],
    )


def test_supplier_tools_exist_in_the_installed_toolkit():
    assert set(SUPPLIER_INVOICE_TOOLS) <= set(toolkit_tool_names())


def test_tool_definitions_are_llm_ready_and_allow_listed():
    toolkit = AgentToolkit(CREDS)
    definitions = toolkit.tool_definitions()
    assert [d["name"] for d in definitions] == list(SUPPLIER_INVOICE_TOOLS)
    create = definitions[0]
    assert create["input_schema"]["type"] == "object"
    assert "items" in create["input_schema"]["properties"]
    json.dumps(definitions)  # must be serialisable for the LLM API


def test_unknown_tools_are_rejected():
    with pytest.raises(ValueError):
        AgentToolkit(CREDS, allowed_tools=["create_invoice", "transfer_everything"])


async def test_calls_outside_the_allow_list_are_refused():
    toolkit = AgentToolkit(CREDS, allowed_tools=["get_invoice"])
    with pytest.raises(PermissionError):
        await toolkit.call("create_order", {})


async def test_create_invoice_through_the_toolkit(fake_http):
    calls, responses = fake_http
    responses[("POST", "/v2/invoicing/invoices")] = FakeResponse(
        201,
        {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/invoicing/invoices/INV2-X"},
    )
    invoice_id = await AgentToolkit(CREDS).create_invoice(_draft())
    assert invoice_id == "INV2-X"
    sent = calls[-1]["json"]
    assert sent["detail"]["invoice_number"] == "SW-GO1-FD-1"
    assert sent["invoicer"] == {"business_name": "FreshDairy SG"}
    assert sent["items"][0]["unit_amount"] == {"currency_code": "SGD", "value": "2.05"}
    assert calls[-1]["url"].startswith("https://api-m.sandbox.paypal.com")


async def test_toolkit_http_errors_become_typed_errors(fake_http):
    _, responses = fake_http
    responses[("POST", "/v2/invoicing/invoices")] = FakeResponse(
        422,
        {
            "name": "UNPROCESSABLE_ENTITY",
            "message": "dup",
            "debug_id": "d1",
            "details": [{"issue": "DUPLICATE_INVOICE_NUMBER"}],
        },
    )
    with pytest.raises(PayPalUnprocessableError) as exc_info:
        await AgentToolkit(CREDS).create_invoice(_draft())
    assert exc_info.value.has_issue("DUPLICATE_INVOICE_NUMBER")
    assert exc_info.value.operation == "toolkit.create_invoice"


def test_draft_mapping_matches_toolkit_parameters():
    from paypal_agent_toolkit.shared.invoices.parameters import CreateInvoiceParameters

    params = draft_to_toolkit_params(_draft())
    CreateInvoiceParameters(**params)  # validates against the toolkit's own schema
