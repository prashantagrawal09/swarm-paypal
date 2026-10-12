# PayPal sandbox setup

This takes about 20 minutes and no real money is involved: the PayPal **sandbox** is a
copy of PayPal with pretend accounts and pretend balances.

You do three things on PayPal's website, then two commands here:

1. [Open the Developer Dashboard](#1-open-the-developer-dashboard)
2. [Make three test accounts](#2-make-three-test-accounts)
3. [Make two apps](#3-make-two-apps)
4. [`make paypal-setup`](#4-give-swarm-the-keys): paste the keys, one question at a time
5. [`make smoke`](#5-run-the-smoke-test): prove every PayPal call works

That is the minimum. [The full demo](#6-the-full-demo-optional) adds two more suppliers and
three more shop owners; anything you leave out runs on Swarm's built-in simulator.

## 1. Open the Developer Dashboard

Go to **https://developer.paypal.com/dashboard/** and log in with your PayPal account.

At the top right there is a **Sandbox / Live** switch. Keep it on **Sandbox** the whole
time. Swarm refuses to talk to Live.

(The page at developer.paypal.com with "Get started", "Payments" and other tiles is the
documentation site. The dashboard is a separate page; use the link above.)

## 2. Make three test accounts

Go to **Testing Tools → Sandbox Accounts**
(https://developer.paypal.com/dashboard/accounts).

Click **Create account** three times:

| # | Account type | Country | This account is |
|---|---|---|---|
| 1 | **Business** | **Singapore** | Swarm itself (the platform). It places the holds, charges, refunds and pays the suppliers. |
| 2 | **Business** | **Singapore** | The supplier FreshDairy SG. It sends invoices and gets paid. |
| 3 | **Personal** | **Singapore** | The owner of Café Mei, a buyer. |

PayPal gives each account a made-up email such as `sb-abc123@business.example.com` (or
`@personal.example.com`). **Write down which email is which**; you'll need all three.

The list already has one or two default accounts. Leave them alone: they usually belong to
another country.

Why Singapore: saving a buyer's PayPal for later ("vault") is available to Singapore
merchants, and Singapore accounts hold Singapore dollars, so nothing needs converting.

**The buyer's password.** You'll log in as the Café Mei owner once, in step 5. In the
account list, click the **⋯** next to that Personal account → **View/Edit Account**. The
**Profile** tab shows the email and a system-generated password. If you can't see the
password, click **Change password** there and set your own.

New sandbox accounts start with a pretend balance, which is all Swarm needs.

## 3. Make two apps

An "app" is how PayPal hands out keys. Each business account needs its own.

Go to **Apps & Credentials** (https://developer.paypal.com/dashboard/applications/sandbox)
and click **Create App**.

**App 1: Swarm Platform**

1. App name: `Swarm Platform`. Type: **Merchant**.
2. Sandbox account: pick the email of business account **#1**.
3. Click **Create App**. You land on the app's page.
4. Scroll down to **Features** (PayPal's own docs call this list *App Feature Options*) and
   tick:
   - **Accept payments**, then open **Advanced options** under it and tick **Vault**
   - **Payouts**
   - **Invoicing**
5. Click **Save** at the bottom.

**App 2: FreshDairy SG**

1. App name: `FreshDairy SG`. Type: **Merchant**.
2. Sandbox account: pick the email of business account **#2**.
3. Create it, tick **Invoicing** under Features, and **Save**.

Each app's page shows a **Client ID** and a **Secret** (click the eye or copy icon to get
the Secret). Leave the two app pages open in browser tabs for the next step.

## 4. Give Swarm the keys

In a terminal, in the `swarm` folder:

```bash
make paypal-setup
```

It asks for each value in turn. Copy it from the dashboard and paste it in:

| It asks for | Where it is |
|---|---|
| Swarm Platform: Client ID, Secret | The Swarm Platform app's page |
| Swarm Platform: account email | Sandbox Accounts, business account #1 |
| FreshDairy SG: Client ID, Secret | The FreshDairy SG app's page |
| FreshDairy SG: account email | Sandbox Accounts, business account #2 |
| Café Mei's owner: email | Sandbox Accounts, the Personal account |

What it does for you:

- creates `.env` (the private settings file; git never sees it) if it isn't there,
- tests every pair of keys with PayPal straight away, and tells you if PayPal rejects them,
- saves as you go, so you can stop with Ctrl+C and run it again later (Enter keeps a value
  you already gave),
- marks as "real" only the shops you gave a buyer email for.

The Secret is hidden while you paste it, so the terminal looks like nothing happened. That
is normal: paste once and press Enter.

To see where you stand at any time, without being asked anything:

```bash
make paypal-check
```

Prefer to edit the file by hand? Copy `.env.example` to `.env` and fill in the
`PAYPAL_PLATFORM_*`, `PAYPAL_SUPPLIER_FRESHDAIRY_*` and `PAYPAL_SHOP_CAFE_MEI_EMAIL` lines.

## 5. Run the smoke test

```bash
make smoke
```

This runs every PayPal call Swarm depends on, for small amounts, against your sandbox: a
hold, a charge for less than the hold, a release, a refund, a payout, an invoice.

Partway through it prints a box that says **ACTION NEEDED** with a
`https://www.sandbox.paypal.com/...` link:

1. Open the link in a **private/incognito window** (so it doesn't clash with your own
   PayPal login).
2. Log in with the **Café Mei owner's sandbox email and password** (from step 2).
3. Approve. You land on a `localhost:3000/connect/return` page, which may not load. That is
   fine: the script notices the approval within a few seconds and carries on.

It ends with a table of PASS / FAIL for each step. Expect one **EXPECTED** row the first
time: PayPal only lets a hold be refreshed after three days, so the "reauthorize" step
shows PayPal refusing exactly as it should. Run `make smoke` again three or more days later
and that step does a real refresh.

The approval is remembered (in `backend/scripts/.smoke_state.json`, and as Café Mei's saved
PayPal in `.env`), so later runs don't need the browser. To approve again as a different
buyer, run `cd backend && .venv/bin/python scripts/paypal_smoke.py --fresh-vault`.

When the table is all PASS (plus that one EXPECTED), run `make seed` and start the app:
Café Mei, FreshDairy SG and the platform now use the real sandbox, and every page labels
them **REAL**.

## 6. The full demo (optional)

The demo story has three suppliers and four "real" shops. To add the rest:

1. In **Sandbox Accounts**, create two more **Business** accounts (PackPro, Johor Farm
   Fresh) and three more **Personal** accounts (the owners of Bakery Lim, Kopi Corner and
   Brew Lab), all **Singapore**.
2. In **Apps & Credentials**, create an app for each new business account, type
   **Merchant**, with **Invoicing** ticked.
3. Run `make paypal-setup` again. Press Enter through what you already gave, answer **y**
   to "Add those now?", and paste the new values. Enter skips any you haven't made.
4. Run `make seed`, start the app, and for each new shop open
   `http://localhost:3000/connect/<shop-code>` (`bakery-lim`, `kopi-corner`, `brew-lab`).
   Log in as that shop's owner and approve the S$1.00 check, which is released straight
   away. That saves the owner's PayPal, as step 5 did for Café Mei.

Johor Farm Fresh is Malaysian in the story, but this version settles in Singapore dollars,
so its sandbox account is a Singapore one too.

## 7. Webhooks (needed for the hosted app, optional on your laptop)

PayPal tells Swarm about payment events by calling a public HTTPS address. On Render that
is the API's own address ([deploy.md](deploy.md#3-paypal-webhooks)). On your laptop you
need a tunnel:

1. `brew install cloudflared`
2. `make backend` in one terminal, then `cloudflared tunnel --url http://localhost:8000` in
   another. Copy the `https://<random>.trycloudflare.com` address it prints.
3. Swarm Platform app → **Webhooks → Add Webhook**. URL:
   `https://<random>.trycloudflare.com/webhooks/paypal`. Events:
   `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`,
   `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`,
   `PAYMENT.PAYOUTSBATCH.SUCCESS`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `VAULT.PAYMENT-TOKEN.CREATED`.
4. Copy the **Webhook ID** into `PAYPAL_WEBHOOK_ID` in `.env` and restart the backend.
5. Run `make smoke`. The backend checks each delivery with PayPal and saves it under
   `backend/var/webhooks/`.
6. To re-check one of them through the smoke test:

   ```bash
   cd backend && .venv/bin/python scripts/paypal_smoke.py --webhook-capture var/webhooks/<event-id>.json
   ```

The tunnel's address changes every time cloudflared restarts; update the webhook when it
does. Events sent from the dashboard's webhook *simulator* can't be verified, so they are
rejected; only events from real sandbox activity pass.

## If something goes wrong

| What you see | What to do |
|---|---|
| `make paypal-setup` says PayPal rejected the keys | The Client ID and Secret must come from the same app, with the dashboard on **Sandbox**. Copy both again. |
| "Couldn't confirm Vault / Payouts / Invoicing" | Open the app, check the feature is ticked under Features, and press **Save**. This is a hint read from the app's token; `make smoke` is the real test. |
| Smoke step 3 or 4 ("Vault: ...") fails, mentioning vault or permissions | **Vault** isn't on for the Swarm Platform app: Features → Accept payments → Advanced options → Vault → Save. Wait a minute and run it again. |
| Smoke step 11 ("Payout S$3") fails with an authorization error | **Payouts** isn't ticked on the Swarm Platform app. |
| Smoke step 11 ("Payout S$3") fails for lack of funds | The platform account's pretend balance ran out. Sandbox Accounts → ⋯ → View/Edit Account → **Funding**, and top it up. |
| The approval page won't let you log in | Use the **Personal** account's email and its sandbox password, in a private window. Your real PayPal login doesn't work there. |
| You approved, but the script keeps waiting | Make sure you clicked the final approve/continue button. It gives up after 10 minutes; just run `make smoke` again. |
| Any step FAILs with a `debug_id` | Send the last 30 lines of the output. The debug ID is what PayPal support (and the logs) key on. |
