# Swarm

> Small shops buy alone and pay retail. Swarm lets them buy together and pay like a chain.
> Every deal, hold, invoice, payout and refund runs through PayPal.

Swarm gives every small food business (cafés, hawker stalls, bakeries) its own agent. The
agents combine their weekly orders, negotiate with supplier agents the way a chain's buyer
would, and use PayPal to hold, pay, refund and settle everything safely. They also help
neighbouring shops: selling surplus stock before it expires and lending supplies in an
emergency.

The demo world is 12 fictional shops and 3 suppliers in Tiong Bahru, Singapore, trading in SGD.

> **Status:** in active development. See [PROGRESS.md](PROGRESS.md) for what works today.

---

## Contents

1. [Why it matters](#why-it-matters)
2. [Features](#features)
3. [Architecture](#architecture)
4. [How Swarm uses PayPal](#how-swarm-uses-paypal)
5. [How Swarm uses AI](#how-swarm-uses-ai)
6. [Tools used](#tools-used)
7. [Setup](#setup)
8. [Demo walkthrough](#demo-walkthrough)
9. [Limitations and production path](#limitations-and-production-path)
10. [Roadmap](#roadmap)
11. [Contributing](#contributing)
12. [License](#license)

---

## Why it matters

A café buying 25 litres of milk a week pays the top tier price. Twelve cafés on the same
street buying 290 litres together get the bottom tier, one delivery run instead of twelve,
and a single invoice that someone actually checks. Swarm gives independent shops that
buying power without asking them to coordinate with each other by hand.

_Full write-up arrives with the submission (phase 8)._

## Features

| | Feature | What happens |
|---|---|---|
| F1 | Weekly group buy | Shop agents forecast needs, pool them, and negotiate live with three supplier agents. |
| F2 | Pay only for what arrived | Holds are placed on order; only delivered quantities are captured. |
| F3 | Invoice checker | Supplier invoices are checked line by line against the awarded quote before anyone pays. |
| F4 | Surplus swap | Stock that is about to expire is sold to a neighbour who is running low. |
| F5 | Emergency borrow | "Out of eggs, need 30 now" is matched to a nearby shop in under two minutes. |
| F6–F9 | Supporting | Demand forecasts, weekly savings report, supplier flash deals, spending limits. |

_Screenshots and GIFs are added in phase 8._

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full diagrams.

```mermaid
flowchart LR
  Owner[Shop owner<br/>Telegram] --> Bot[Telegram bot]
  Judge[Browser] --> Web[Next.js web app]
  Bot --> API[FastAPI backend]
  Web -- REST + SSE --> API
  API --> Agents[Shop / Supplier / Coordinator / Claims agents]
  Agents --> Money[Money engine<br/>rules, state machines, ledger]
  Money --> PP[PayPal gateway<br/>real sandbox or simulated]
  PP --> PayPal[(PayPal REST APIs)]
  API --> DB[(PostgreSQL)]
```

## How Swarm uses PayPal

| Capability | Where | Why |
|---|---|---|
| Save PayPal for future use (vault) | `/connect/[shopId]`, `app/paypal/client.py` | One-time owner approval so the shop's agent can place weekly holds without the owner logging in. |
| Authorize (hold) | Wednesday holds | Money is reserved when the group order is awarded, not taken. |
| Partial capture with `final_capture` | Thursday delivery | Shops pay only for what arrived; the rest of the hold is released. |
| Void | Cancelled orders | Every hold is released if a group order is cancelled. |
| Reauthorize | Late deliveries | Holds older than the 3-day honor period are refreshed before capture. |
| Refund | Claims | Damaged or expired goods are refunded from the original capture. |
| Payouts | Supplier settlement, swap sellers | The platform pays suppliers (minus a 2% fee) and shops that sold surplus. |
| Invoicing | Supplier agents (via PayPal Agent Toolkit) | Suppliers bill the platform; Swarm checks every line before paying. |
| Webhooks | `/webhooks/paypal` | Signature-verified, de-duplicated payment events keep the ledger in sync. |

The PayPal Agent Toolkit handles invoicing (create, send, get, record payment). Holds,
captures, voids, reauthorizations, refunds, payouts and vaulting go through Swarm's own typed
REST client, because the toolkit's order tools only support immediate capture. Details and
verified field names are in [docs/paypal-notes.md](docs/paypal-notes.md).

## How Swarm uses AI

**AI suggests, code decides.** Language models write messages, explain forecasts, choose
between valid options and parse messy owner input. They never decide an amount of money:
every amount that reaches PayPal is computed and validated by deterministic code (spending
limits, supplier price floors, capture ≤ authorization, idempotency keys). Messages between
agents are treated as untrusted data and can never change an agent's rules.

_Agent diagram and details arrive in phase 3._

## Tools used

- **PayPal REST APIs** (sandbox): Orders v2, Payments v2, Payouts v1, Invoicing v2, Webhooks v1.
- **PayPal Agent Toolkit** (Python): invoicing actions for supplier agents.
- **LLM:** Anthropic API (model configurable via ANTHROPIC_MODEL).
- **Backend:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx, PostgreSQL.
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, AG Grid Community.
- **Messaging:** Telegram Bot API (python-telegram-bot).
- **Hosting:** Render.

## Setup

### Prerequisites

- Python 3.11, Node.js 22, Docker
- A PayPal developer account for the sandbox (see [docs/paypal-setup.md](docs/paypal-setup.md))

### Run it locally

```bash
cp .env.example .env          # fill in PayPal / LLM / Telegram keys as you need them
make setup                    # venv + Python deps + npm install + git hooks
make db-up                    # Postgres on localhost:5434
make migrate                  # apply database migrations
make seed                     # 12 shops, 3 suppliers, catalog, 8 weeks of history
make backend                  # API on http://localhost:8000
make frontend                 # web app on http://localhost:3000
```

### Prove the PayPal integration

```bash
make smoke-sim                # every PayPal step against the simulated client
make smoke                    # the same steps against the real PayPal sandbox
```

`make smoke` prints an approval link partway through; open it, log in as the sandbox buyer
and approve. It ends with a PASS/FAIL table.

### Checks

```bash
make check                    # ruff, mypy, eslint, tsc, prettier and pytest
```

## Demo walkthrough

_Arrives with `docs/demo-script.md` in phase 8._

## Limitations and production path

- In production, this would use PayPal's multiparty / marketplace setup so funds go directly
  to suppliers with the platform fee taken automatically.
- Prices for the Malaysian supplier are quoted in SGD; cross-border MYR settlement is on the roadmap.
- Sales history is generated; a real deployment would read it from the shops' POS systems.

## Roadmap

Reverse auctions, group service deals (pest control, cleaning), price watchdog, supplier
report cards, weekly shop-to-shop netting, menu margin coach, waste tracker, supplier portal
onboarding from price-list photos, cross-border MYR settlement, multiparty payments.

## Contributing

- Conventional commits: `feat:`, `fix:`, `chore:`, `test:`, `docs:`.
- `make check` must pass before committing.
- Git hooks live in `.githooks/` and are enabled by `make setup` (or `make hooks`), which
  runs `git config core.hooksPath .githooks`. The `commit-msg` hook strips co-author trailers
  and "generated with" tool lines so the history stays clean and consistent.
- Secrets live only in `.env`, which is git-ignored. Add every new variable to `.env.example`
  with a comment.

## License

[MIT](LICENSE)
