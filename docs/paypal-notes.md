# PayPal integration notes

Every PayPal call Swarm makes, the fields it sends and reads, and what we learned about the
sandbox. Field names were checked against PayPal's published OpenAPI specs
([paypal/paypal-rest-api-specifications](https://github.com/paypal/paypal-rest-api-specifications):
`checkout_orders_v2` 2.32, `payments_payment_v2` 2.12, `payments_payouts_batch_v1` 1.9,
`invoicing_v2` 2.6, `notifications_webhooks_v1` 1.11) and the developer docs on 2026-10-06.

Code: request builders and response parsers live in one place,
[`backend/app/paypal/payloads.py`](../backend/app/paypal/payloads.py). The real client is
[`client.py`](../backend/app/paypal/client.py), the simulator
[`simulated.py`](../backend/app/paypal/simulated.py).

## Conventions used for every call

| Topic | What Swarm does | Source |
|---|---|---|
| Base URL | `https://api-m.sandbox.paypal.com`. The client refuses the live URL. | docs |
| Auth | `POST /v1/oauth2/token`, HTTP Basic `client_id:secret`, body `grant_type=client_credentials`. Token cached until 120 s before `expires_in`; on a 401 the token is refreshed once and the call repeated. | docs |
| Idempotency | `PayPal-Request-Id: <idempotency key>` on every mutation. Orders, Payments and Payouts declare this header in their specs. A replay with the same ID returns the original result. | specs |
| Full responses | `Prefer: return=representation` on Orders, Payments and Invoicing calls. Without it, several endpoints return only a link or an empty 204. | specs |
| Retries | Only for GETs and for mutations that carry a request ID, and only on network errors, 409 `PREVIOUS_REQUEST_IN_PROGRESS`, 429 and 5xx. Backoff 0.5 s, 1 s, 2 s (or `Retry-After`). A 4xx business error is never retried. | specs |
| Errors | Bodies look like `{name, message, debug_id, details[{issue, description, field}]}` (OAuth: `{error, error_description}`). Mapped to typed exceptions in `errors.py` that keep `debug_id` and the issue codes. | specs |
| Money | `{currency_code, value}` with value as a decimal string (`"12.30"`). **Payouts is the exception: `{currency, value}`.** Swarm keeps integer cents and only converts at this boundary (`Money.to_paypal()` / `to_payouts()`). | specs |

## Orders v2

### Create order: first approval with "save PayPal" (vault)

`POST /v2/checkout/orders`

```json
{
  "intent": "AUTHORIZE",
  "purchase_units": [{"reference_id": "...", "amount": {"currency_code": "SGD", "value": "10.00"}, "description": "..."}],
  "payment_source": {
    "paypal": {
      "attributes": {"vault": {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT"}},
      "experience_context": {
        "brand_name": "Swarm", "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW",
        "return_url": "...", "cancel_url": "..."
      }
    }
  }
}
```

- `usage_type` is **required** in the vault object (`MERCHANT` or `PLATFORM`). Optional fields we
  leave out on purpose: `customer_type`, `usage_pattern`, `permit_multiple_payment_tokens`.
- Response status is `PAYER_ACTION_REQUIRED`. The buyer link is `links[rel="payer-action"]` when
  `payment_source.paypal.experience_context` is used (older integrations get `rel="approve"`).
  The parser accepts either.
- Vaulting PayPal during purchase is listed as supported for **Singapore**. Sandbox needs the app's
  **Accept payments → Advanced → Vault** feature enabled.

### Authorize order

`POST /v2/checkout/orders/{id}/authorize` with no body. Read:
- `purchase_units[].payments.authorizations[]` → `id`, `status`, `amount`, `create_time`,
  `expiration_time`;
- `payment_source.paypal.attributes.vault` → `id` (the vault ID to keep), `status`
  (`VAULTED`, or `APPROVED` if saving is still pending), `customer.id`;
- `payment_source.paypal.email_address`.

### Create order with the saved wallet (buyer not present)

`POST /v2/checkout/orders` with `payment_source: {"paypal": {"vault_id": "..."}}` and no
experience context. PayPal's docs show the `CAPTURE` version completing immediately
(`status: COMPLETED` with the capture inside). For `AUTHORIZE` we expect the same, with the
authorization inside. **If PayPal instead returns an order without an authorization, the
smoke test and the money engine call `/authorize` explicitly.** The first real smoke run
confirms which path the sandbox takes (see "To confirm on the first real run").

## Payments v2

| Call | Request | Notes |
|---|---|---|
| `GET /v2/payments/authorizations/{id}` | none | `status` ∈ `CREATED, CAPTURED, DENIED, PARTIALLY_CAPTURED, VOIDED, PENDING` |
| `POST /v2/payments/authorizations/{id}/capture` | `{amount, final_capture, invoice_id?, note_to_payer?}` | `final_capture: true` on a partial amount closes the authorization and releases the rest. Errors: `MAX_CAPTURE_AMOUNT_EXCEEDED`, `AUTHORIZATION_EXPIRED`, `PREVIOUS_REQUEST_IN_PROGRESS`. Capture `status` ∈ `COMPLETED, DECLINED, PARTIALLY_REFUNDED, PENDING, REFUNDED, FAILED`. |
| `POST /v2/payments/authorizations/{id}/void` | no body | `204 No Content` by default, `200` with the authorization when `Prefer: return=representation`. Error `PREVIOUSLY_CAPTURED` (409/422). |
| `POST /v2/payments/authorizations/{id}/reauthorize` | `{amount}` only | Allowed from day 4 to day 29 after the original authorization (after the 3-day honor period). Too early gives `REAUTHORIZATION_TOO_SOON`. Returns a **new** authorization ID with a fresh 3-day honor period. The amount limit depends on the region (US: up to 115%, at most +US$75). PayPal's spec says several reauthorizations are allowed within the 29 days. |
| `GET /v2/payments/captures/{id}` | none | |
| `POST /v2/payments/captures/{id}/refund` | `{amount?, note_to_payer?, invoice_id?}` | An **empty body refunds the full remaining amount**. Errors: `REFUND_AMOUNT_EXCEEDED`, `TRANSACTION_DISPUTED`. Refund `status` ∈ `CANCELLED, FAILED, PENDING, COMPLETED`. |

**Honor period design:** a group order captures within 3 days of the hold. If delivery slips past
day 3, the money engine (phase 2) reauthorizes first and captures against the new ID.

## Payouts v1

`POST /v1/payments/payouts`

```json
{
  "sender_batch_header": {"sender_batch_id": "...", "recipient_type": "EMAIL", "email_subject": "..."},
  "items": [{"recipient_type": "EMAIL", "receiver": "...", "amount": {"currency": "SGD", "value": "3.00"},
             "sender_item_id": "...", "recipient_wallet": "PAYPAL", "note": "..."}]
}
```

- `201` returns only `batch_header` with `batch_status: PENDING`. Poll
  `GET /v1/payments/payouts/{payout_batch_id}` for `SUCCESS` and per-item `transaction_status`.
- **Two layers of idempotency:** `PayPal-Request-Id`, plus `sender_batch_id`, which PayPal rejects
  if it was used in the last 30 days. PayPal says a 5xx can be safely retried with the same
  `sender_batch_id`.
- Batch status ∈ `DENIED, PENDING, PROCESSING, SUCCESS, CANCELED`. Item status ∈ `SUCCESS, FAILED,
  PENDING, UNCLAIMED, RETURNED, ONHOLD, BLOCKED, REFUNDED, REVERSED`. `UNCLAIMED` means the
  receiver email has no PayPal account.
- No `Prefer` header (not part of the Payouts API).

## Invoicing v2 (supplier side)

| Call | Request | Notes |
|---|---|---|
| `POST /v2/invoicing/invoices` | `{detail{invoice_number, invoice_date, currency_code, payment_term{term_type}, reference?, note?}, invoicer{business_name?, email_address?}, primary_recipients[{billing_info{email_address, business_name?}}], items[{name, quantity (string), unit_amount, unit_of_measure: QUANTITY, description?}]}` | Creates a **DRAFT**. Without `Prefer: return=representation` the response is just a link (`{rel, href, method}`); we read the ID from `href` and GET the invoice. |
| `POST /v2/invoicing/invoices/{id}/send` | `{send_to_recipient, send_to_invoicer, subject?, note?}` | Returns a link (200) or 202 when scheduled. |
| `GET /v2/invoicing/invoices/{id}` | none | `status` ∈ `DRAFT, SENT, SCHEDULED, PAID, MARKED_AS_PAID, CANCELLED, REFUNDED, PARTIALLY_PAID, PARTIALLY_REFUNDED, MARKED_AS_REFUNDED, UNPAID, PAYMENT_PENDING, AUTO_CANCELLED, PAID_EXTERNAL`. |
| `POST /v2/invoicing/invoices/{id}/payments` | `{method, payment_date (YYYY-MM-DD), amount, note?}` | Records an external payment and returns `{payment_id}`. The invoice becomes paid (often shown as `MARKED_AS_PAID`) or `PARTIALLY_PAID`. `method` ∈ `BANK_TRANSFER, CASH, CHECK, CREDIT_CARD, DEBIT_CARD, PAYPAL, WIRE_TRANSFER, OTHER`. |

- The Invoicing spec does **not** declare `PayPal-Request-Id`. We send it anyway (harmless), but
  real protection against duplicates is the **unique `invoice_number` per invoicer** (PayPal
  rejects duplicates with `DUPLICATE_INVOICE_NUMBER`). Swarm derives invoice numbers from the
  group order and revision, so a retried create cannot make a second invoice. Max length 25.
- `quantity` is a string with up to 5 decimals.

## Webhooks v1

`POST /v1/notifications/verify-webhook-signature`

```json
{"auth_algo": "...", "cert_url": "...", "transmission_id": "...", "transmission_sig": "...",
 "transmission_time": "...", "webhook_id": "...", "webhook_event": <the event, exactly as received>}
```

- The five values come from the `PAYPAL-AUTH-ALGO`, `PAYPAL-CERT-URL`, `PAYPAL-TRANSMISSION-ID`,
  `PAYPAL-TRANSMISSION-SIG` and `PAYPAL-TRANSMISSION-TIME` headers (case-insensitive).
- Response: `{verification_status: SUCCESS | FAILURE}`.
- **Use the raw body.** PayPal's docs warn that parsing and re-serialising the event can fail
  verification. Swarm builds the envelope by hand and splices the raw request bytes in as
  `webhook_event` (`payloads.verify_webhook_body`).
- **Mock events from the dashboard's webhook simulator cannot be verified with this API**
  (PayPal docs). Proving verification needs a real event delivered to a public HTTPS URL on
  port 443 (a tunnel in development).
- Unverified deliveries get HTTP 400 (PayPal retries non-2xx deliveries).

## PayPal Agent Toolkit

- Package: `paypal-agent-toolkit` **1.11.0** (Python). It has adapters for OpenAI Agents,
  LangChain, CrewAI and Bedrock, and hard-pins `openai-agents==0.0.2`, `langchain==0.3.23` and
  `crewai-tools==0.13.2`. Swarm installs it with `--no-deps` and uses the framework-neutral core
  (`paypal_agent_toolkit.shared.api.PayPalAPI.run(method, params)` plus the `tools` registry).
- **Used for:** `create_invoice`, `send_invoice`, `get_invoice`, `list_invoices`,
  `record_payment_for_invoice`, `cancel_sent_invoice` (the supplier agents' allow-list).
- **Not usable for Swarm's core flow:** its `create_order` hardcodes `intent: CAPTURE`, and it has
  no authorize, void, reauthorize, capture-refund, payouts or vault tools. Those go through
  `PayPalClient`.
- Behaviour to know about: it is synchronous (`requests`), so Swarm runs calls in a worker thread.
  It fetches a fresh OAuth token for every call (no caching). It sends no `PayPal-Request-Id`.
  `send_invoice` forwards unset fields as `null`, so Swarm always passes every field.
- Tool schemas come from its Pydantic models (`args_schema.model_json_schema()`) and convert
  directly into LLM tool definitions (`AgentToolkit.tool_definitions()`).

## Simulator-only issue codes

The simulator uses PayPal's documented issue codes where they exist (`MAX_CAPTURE_AMOUNT_EXCEEDED`,
`AUTHORIZATION_EXPIRED`, `PREVIOUSLY_CAPTURED`, `REAUTHORIZATION_TOO_SOON`, `AUTH_CURRENCY_MISMATCH`,
`REFUND_AMOUNT_EXCEEDED`, `ORDER_NOT_APPROVED`, `ORDER_ALREADY_AUTHORIZED`,
`DUPLICATE_INVOICE_NUMBER`). These codes are its own invention; real PayPal may use different
codes for the same case: `AUTHORIZATION_SUPERSEDED` (capturing an authorization that was
reauthorized), `AUTHORIZATION_ALREADY_COMPLETED`, `PREVIOUSLY_VOIDED`,
`REAUTHORIZATION_AMOUNT_EXCEEDED`, `INVALID_VAULT_ID`, `CAPTURE_FULLY_REFUNDED`,
`SENDER_BATCH_ID_ALREADY_USED`, `INVALID_INVOICE_STATUS`, `PAYMENT_AMOUNT_INVALID`,
`ORDER_NOT_APPROVABLE`, `CURRENCY_MISMATCH`, `INVALID_AMOUNT`.

The simulator is deliberately stricter than PayPal in one place: it never allows capturing more
than the authorized amount, even though PayPal allows up to 115% in some regions. Swarm's rule
is the same.

## To confirm on the first real run

The smoke test reports these; update this file with what the sandbox actually does.

- [ ] Does a vaulted `AUTHORIZE` order come back `COMPLETED` with the authorization inside, or
      does it need an explicit `/authorize`?
- [ ] Is `method: PAYPAL` accepted when recording an invoice payment, or only `OTHER` (the smoke
      test falls back automatically and reports which one worked)?
- [ ] Does a forged webhook come back as `FAILURE` or as a 4xx error? (Both count as rejected.)
- [ ] How long do payout batches take to move from `PENDING` to `SUCCESS` in the sandbox?
- [ ] Invoice status right after `send`: `SENT` or `UNPAID`?
- [ ] Reauthorization after day 3 on a vaulted-wallet authorization (needs a second run 3+ days
      later).
