"""Adapter for the PayPal Agent Toolkit (`paypal-agent-toolkit`, Python).

Swarm's supplier agents create, send, read and settle invoices through the toolkit. The
toolkit ships adapters for OpenAI Agents, LangChain, CrewAI and Bedrock but none for our
LLM SDK, so this module uses its framework-neutral core (`paypal_agent_toolkit.shared`):

- `tool_definitions()` turns the toolkit's tool registry into LLM tool schemas
  (`name`, `description`, `input_schema`), filtered to an allow-list.
- `call()` runs one tool after checking the allow-list. The toolkit is synchronous
  (requests), so calls run in a worker thread.
- `create_invoice()` / `send_invoice()` / `get_invoice()` / `record_payment()` are typed
  helpers the supplier agent's deterministic code uses; amounts always come from Swarm's
  money engine, never from model output.

What the toolkit does NOT cover for Swarm (its order tools only capture immediately) goes
through `PayPalClient`: authorize, partial capture, void, reauthorize, refund, payouts,
vaulting and webhook verification.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import date
from typing import Any

from app.money.amount import Money
from app.paypal import payloads
from app.paypal.credentials import PayPalCredentials
from app.paypal.errors import PayPalError, PayPalTransportError, error_from_response
from app.paypal.interface import Invoice, InvoiceDraft, InvoicePaymentMethod

try:
    import requests
    from paypal_agent_toolkit.shared.api import PayPalAPI
    from paypal_agent_toolkit.shared.configuration import Context
    from paypal_agent_toolkit.shared.tools import tools as _TOOLKIT_TOOLS

    TOOLKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when the toolkit is not installed
    TOOLKIT_AVAILABLE = False
    _TOOLKIT_TOOLS = []

# Invoice actions a supplier agent may take. Nothing that moves money is on this list.
SUPPLIER_INVOICE_TOOLS: tuple[str, ...] = (
    "create_invoice",
    "send_invoice",
    "get_invoice",
    "list_invoices",
    "record_payment_for_invoice",
    "cancel_sent_invoice",
)


def toolkit_tool_names() -> list[str]:
    return [str(tool["method"]) for tool in _TOOLKIT_TOOLS]


class AgentToolkitUnavailable(RuntimeError):
    pass


class AgentToolkit:
    """PayPal Agent Toolkit bound to one PayPal account (for example a supplier's app)."""

    def __init__(
        self,
        credentials: PayPalCredentials,
        *,
        allowed_tools: Iterable[str] = SUPPLIER_INVOICE_TOOLS,
    ) -> None:
        if not TOOLKIT_AVAILABLE:
            raise AgentToolkitUnavailable(
                "paypal-agent-toolkit is not installed: "
                "pip install --no-deps -r requirements-toolkit.txt"
            )
        self.credentials = credentials
        self.label = credentials.label
        self._tools = {str(tool["method"]): tool for tool in _TOOLKIT_TOOLS}
        self.allowed_tools = tuple(allowed_tools)
        unknown = set(self.allowed_tools) - set(self._tools)
        if unknown:
            raise ValueError(f"Unknown PayPal Agent Toolkit tools: {sorted(unknown)}")
        self._api = PayPalAPI(
            client_id=credentials.client_id,
            secret=credentials.client_secret,
            context=Context(sandbox=True, source="SWARM"),
        )

    # -- LLM-facing ----------------------------------------------------------------------

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Allow-listed toolkit tools as LLM tool definitions."""
        definitions = []
        for name in self.allowed_tools:
            tool = self._tools[name]
            definitions.append(
                {
                    "name": name,
                    "description": str(tool["description"]),
                    "input_schema": tool["args_schema"].model_json_schema(),
                }
            )
        return definitions

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        """Run one allow-listed toolkit tool and return PayPal's JSON response."""
        if method not in self.allowed_tools:
            raise PermissionError(f"Toolkit tool {method!r} is not allowed for {self.label}")
        try:
            result = await asyncio.to_thread(self._api.run, method, params)
        except requests.HTTPError as exc:
            response = exc.response
            body: Any = None
            if response is not None:
                try:
                    body = response.json()
                except ValueError:
                    body = None
            status = response.status_code if response is not None else 500
            raise error_from_response(status, body, operation=f"toolkit.{method}") from exc
        except requests.RequestException as exc:
            raise PayPalTransportError(str(exc), operation=f"toolkit.{method}") from exc
        except RuntimeError as exc:  # the toolkit raises RuntimeError when OAuth fails
            raise PayPalError(str(exc), operation=f"toolkit.{method}") from exc
        return json.loads(result) if isinstance(result, str) and result else result

    # -- typed helpers for deterministic code -------------------------------------------

    async def create_invoice(self, draft: InvoiceDraft) -> str:
        """Create a DRAFT invoice; returns its PayPal invoice ID."""
        data = await self.call("create_invoice", draft_to_toolkit_params(draft))
        invoice_id = data.get("id") or payloads.invoice_id_from_link(data)
        if not invoice_id:
            raise PayPalError("Toolkit created an invoice but returned no ID", raw=data)
        return str(invoice_id)

    async def send_invoice(self, invoice_id: str, *, note: str = "Invoice from Swarm") -> None:
        # The toolkit forwards every field, including unset ones as null; pass them all.
        await self.call(
            "send_invoice",
            {
                "invoice_id": invoice_id,
                "note": note,
                "send_to_recipient": True,
                "additional_recipients": [],
            },
        )

    async def cancel_invoice(
        self, invoice_id: str, *, note: str = "Replaced by a corrected invoice"
    ) -> None:
        await self.call(
            "cancel_sent_invoice",
            {
                "invoice_id": invoice_id,
                "note": note,
                "send_to_recipient": True,
                "additional_recipients": [],
            },
        )

    async def get_invoice(self, invoice_id: str) -> Invoice:
        return payloads.parse_invoice(await self.call("get_invoice", {"invoice_id": invoice_id}))

    async def record_payment(
        self,
        invoice_id: str,
        *,
        amount: Money,
        payment_date: date,
        method: InvoicePaymentMethod,
        note: str | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "invoice_id": invoice_id,
            "method": method,
            "payment_date": payment_date.isoformat(),
            "amount": amount.to_paypal(),
        }
        if note:
            params["note"] = note
        data = await self.call("record_payment_for_invoice", params)
        return str(data.get("payment_id", ""))


def draft_to_toolkit_params(draft: InvoiceDraft) -> dict[str, Any]:
    """Map an `InvoiceDraft` to the toolkit's flat `CreateInvoiceParameters` shape."""
    recipient: dict[str, Any] = {"email_address": draft.recipient_email}
    if draft.recipient_business_name:
        recipient["business_name"] = draft.recipient_business_name
    params: dict[str, Any] = {
        "currency_code": draft.currency,
        "invoice_number": draft.invoice_number,
        "invoice_date": draft.invoice_date.isoformat(),
        "primary_recipients": [{"billing_info": recipient}],
        "items": [payloads.invoice_line_body(line) for line in draft.lines],
    }
    optional = {
        "reference": draft.reference,
        "note": draft.note,
        "invoicer_business_name": draft.invoicer_business_name,
        "invoicer_email_address": draft.invoicer_email,
    }
    params.update({key: value for key, value in optional.items() if value})
    return params
