# PayPal sandbox setup

Everything here happens in the PayPal Developer Dashboard (https://developer.paypal.com,
**Sandbox** mode). Nothing touches real money.

Swarm needs **one platform account**, **three supplier accounts** and **four shop (buyer)
accounts**. To run the phase 1 smoke test you only need the first three rows in the table.

| Sandbox account | Type | Country | Used for | Needed for smoke test |
|---|---|---|---|---|
| Swarm Platform | Business | Singapore | Merchant of record: places holds, captures, refunds, sends payouts, receives supplier invoices | Yes |
| FreshDairy SG | Business | Singapore | Supplier: creates and sends invoices, receives payouts | Yes |
| Café Mei (owner) | Personal | Singapore | Buyer: approves "save PayPal" once, then gets holds without logging in | Yes |
| PackPro | Business | Singapore | Supplier | Later |
| Johor Farm Fresh | Business | Singapore* | Supplier | Later |
| Bakery Lim, Kopi Corner, Brew Lab (owners) | Personal | Singapore | Buyers (REAL shops) | Later |

\* Johor Farm Fresh is Malaysian in the story, but v1 settles in SGD, so a Singapore sandbox
account avoids currency-conversion holds. MYR settlement is on the roadmap.

**Why Singapore:** PayPal's "save PayPal for future purchases" (vault) is supported for
Singapore merchants, and accounts created in Singapore hold SGD, so SGD captures and payouts
settle without a manual "accept this currency" step.

## 1. Create the sandbox accounts

1. Developer Dashboard → **Testing Tools → Sandbox Accounts → Create account**.
2. For each account in the table: choose **Business** or **Personal**, country **Singapore**,
   then **Create**.
3. For **personal** accounts, open the account (⋯ → **View/Edit account**) and make sure it has a
   PayPal balance (for example S$5,000) or a card attached, so holds can be authorized.
4. For the **platform** account, make sure it has an SGD balance (payouts are paid from it).
5. Note each account's email (looks like `sb-xxxxx@business.example.com`). For the buyer, also
   note the password shown under **View/Edit account**: you log in with it to approve.

## 2. Create the REST apps

Developer Dashboard → **Apps & Credentials** → make sure **Sandbox** is selected → **Create App**.

**Swarm Platform app**
1. Name: `Swarm Platform`, type **Merchant**, sandbox account: **Swarm Platform**.
2. Open the app → **Features** (Sandbox app settings) and enable:
   - **Accept payments** → expand **Advanced options** → tick **Vault** (needed to save the
     buyer's PayPal for future holds),
   - **Payouts**,
   - **Invoicing**.
3. Copy **Client ID** and **Secret**.

**Supplier apps** (one per supplier; FreshDairy SG is enough for the smoke test)
1. Name: `FreshDairy SG`, type **Merchant**, sandbox account: **FreshDairy SG**.
2. Enable **Invoicing**.
3. Copy **Client ID** and **Secret**.

## 3. Fill in `.env`

```bash
cp .env.example .env
```

```dotenv
PAYPAL_ENV=sandbox
PAYPAL_CURRENCY=SGD
PAYPAL_PLATFORM_CLIENT_ID=...            # Swarm Platform app
PAYPAL_PLATFORM_CLIENT_SECRET=...
PAYPAL_PLATFORM_EMAIL=sb-...@business.example.com
PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_ID=... # FreshDairy SG app
PAYPAL_SUPPLIER_FRESHDAIRY_CLIENT_SECRET=...
PAYPAL_SUPPLIER_FRESHDAIRY_EMAIL=sb-...@business.example.com
```

`SMOKE_PAYOUT_RECEIVER` is optional; the smoke payout goes to the FreshDairy email by default.

## 4. Run the smoke test

```bash
make smoke
```

Partway through, step 3 prints a box that says **ACTION NEEDED** with a
`https://www.sandbox.paypal.com/...` link:

1. Open the link in a browser (a private window avoids clashing with your developer login).
2. Log in with the **Café Mei personal sandbox account** email and password.
3. Approve. You land on a `localhost:3000/connect/return` page that may not load yet; that is
   fine. The script notices the approval within a few seconds and carries on.

The vault ID is saved in `backend/scripts/.smoke_state.json`, so later runs skip the browser
step (use `--fresh-vault` to approve again).

**Reauthorization:** PayPal only allows reauthorizing a hold after its 3-day honor period. On
the first run that step shows `EXPECTED` (PayPal answered `REAUTHORIZATION_TOO_SOON`) and the
script keeps that hold aside. Run `make smoke` again 3+ days later and the step does a real
reauthorization.

## 5. Webhooks (optional for phase 1, needed from phase 2)

PayPal only delivers webhooks to a public HTTPS URL on port 443, and events from the dashboard's
webhook simulator **cannot** be verified with the verify API. To prove verification with a
real event:

1. `brew install cloudflared`
2. `make backend` in one terminal, then `cloudflared tunnel --url http://localhost:8000` in
   another. Copy the `https://<random>.trycloudflare.com` URL.
3. Swarm Platform app → **Webhooks → Add Webhook**: URL
   `https://<random>.trycloudflare.com/webhooks/paypal`, events:
   `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`,
   `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`,
   `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `VAULT.PAYMENT-TOKEN.CREATED`.
4. Copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID` and restart the backend.
5. Run `make smoke`. The backend verifies each delivery and saves it under
   `backend/var/webhooks/`.
6. Re-verify one of them through the smoke test:

   ```bash
   cd backend && .venv/bin/python scripts/paypal_smoke.py --webhook-capture var/webhooks/<event-id>.json
   ```

The quick-tunnel URL changes every time cloudflared restarts; update the webhook URL when it
does. The deployed app (phase 8) uses its permanent Render URL instead.
