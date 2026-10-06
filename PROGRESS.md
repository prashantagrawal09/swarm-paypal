# Progress

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation | Done |
| 1 | Prove PayPal | Done (simulated); waiting on your sandbox run |
| 2 | Data model and money engine | Done |
| 3 | Agents and negotiation | Done |
| 4 | Telegram bot | Not started |
| 5 | Web app | Not started |
| 6 | Hero features F2–F5 | Not started |
| 7 | Supporting features and polish | Not started |
| 8 | Deploy and submission | Not started |

---

## Phase 0: Foundation

**Built**
- Repo layout from `SWARM_SPEC.md` section 4, its own git repository (the home directory is
  also a git repo, so Swarm must never be committed from there).
- `docker-compose.yml`: Postgres 16 on host port **5434** (5432/5433 are used by other local
  projects), plus a `swarm_test` database for the test suite.
- Backend: Python 3.11 venv, FastAPI app with `/` and `/health` (reports DB status without
  failing), settings from `.env`, Swarm Clock, SQLAlchemy 2 async session, declarative base with
  UUID + timestamp mixins and constraint naming, Alembic wired to the app settings.
- Frontend: Next.js 16 (App Router) + TypeScript + Tailwind v4, header with a live backend
  status pill, landing page, placeholder routes for `/live`, `/demo`, `/shop/[id]`,
  `/supplier/[id]`, `/connect/[shopId]`, and a REAL/Simulated badge component.
- Tooling: ruff, mypy, pytest (+ asyncio, respx), eslint, prettier, `Makefile`, GitHub Actions CI
  (runs once the repo is pushed), MIT license, README skeleton, `.env.example`.
- `.githooks/commit-msg` with `core.hooksPath` set.

**Works**
- `make check`: ruff, mypy, eslint, tsc, prettier, pytest (10 tests) all green.
- `alembic upgrade head` / `alembic check` run against the local database.
- `npm run build` succeeds.

**Pending**
- Everything from phase 1 on.

**Manual steps for you**
- None.

---

## Phase 1: Prove PayPal

**Built**
- `app/money/amount.py`: `Money` value type (integer cents + currency; exact PayPal decimal
  strings both ways; Payouts' `{currency, value}` shape; currency-safe arithmetic).
- `app/paypal/interface.py`: the `PayPalGateway` contract and typed request/result objects.
- `app/paypal/payloads.py`: the one place that builds PayPal request bodies and parses
  responses. Every field was checked against PayPal's OpenAPI specs and docs.
- `app/paypal/client.py`: real async client. Cached OAuth with one refresh on 401,
  `PayPal-Request-Id` on every mutation, `Prefer: return=representation`, safe retries
  (idempotent calls only), typed errors carrying `debug_id` and issue codes, refuses live.
- `app/paypal/simulated.py`: in-memory PayPal with PayPal's rules (capture limits,
  final_capture, void after capture, the 3-day honor period and 29-day validity for
  reauthorization, refund limits, payout batch IDs, invoice lifecycle, idempotent replays,
  HMAC-signed webhooks, fault injection). `SIM-` IDs. Reads back through the same parsers.
- `app/paypal/accounts.py`: credentials by env prefix and a `GatewayRegistry` that picks the
  real or simulated gateway per account.
- `app/paypal/toolkit.py`: PayPal Agent Toolkit adapter. Allow-listed invoice tools exposed as
  LLM tool schemas, plus typed helpers. Installed `--no-deps` (see `requirements-toolkit.txt`).
- `app/paypal/webhooks.py`: `POST /webhooks/paypal` verifies with PayPal using the raw body,
  returns 400 for unverified deliveries, and saves verified deliveries in development so they
  can be replayed.
- `scripts/paypal_smoke.py` (`make smoke`, `make smoke-sim`): 17 steps with a PASS/FAIL table,
  a JSON report, a saved vault so the browser approval is needed only once, and a hold kept
  aside so a run 3+ days later can prove a real reauthorization.
- Docs: `docs/paypal-notes.md` (verified fields, quirks, toolkit coverage, open questions) and
  `docs/paypal-setup.md` (exact sandbox accounts, app settings, webhook tunnel).

**Works**
- 76 backend tests pass: respx-mocked request shapes for every endpoint, token caching and
  refresh, retry and no-retry rules, error mapping, the simulator's money rules, the webhook
  endpoint, the toolkit adapter (schemas, allow-list, HTTP errors) and the full smoke run in
  simulated mode.
- `make smoke-sim`: 17/17 PASS.
- `make smoke` without credentials stops with a clear list of the missing `.env` keys.

**Pending**
- **The real sandbox run** (needs your credentials and one browser approval). The items to
  confirm on that run are listed at the end of `docs/paypal-notes.md`.
- Real-event webhook verification needs a tunnel (cloudflared); optional until phase 2.
- `/sim/approve/{order_id}` (the simulated approval link) gets a real page with the connect flow
  in phase 5.

**Manual steps for you**
1. Follow `docs/paypal-setup.md` sections 1 to 3: create the Swarm Platform business account, the
   FreshDairy SG business account and one personal buyer account (all Singapore). Create the
   two REST apps (Platform: Accept payments + Vault, Payouts, Invoicing; FreshDairy: Invoicing).
   Put the IDs, secrets and emails in `.env`.
2. Run `make smoke`. When it prints **ACTION NEEDED**, open the link, log in as the personal
   sandbox buyer and approve.
3. Send me the final table (or `backend/var/smoke-report.json`) and I'll update
   `docs/paypal-notes.md` with what the sandbox actually did.

---

## Phase 2: Data model and money engine

**Built**
- **Data model:** 22 tables, one Alembic migration (it upgrades and downgrades cleanly).
  DB-level CHECK constraints for enums and money invariants (capture <= hold, refund <=
  capture, delivered <= ordered). Refinements to the spec's table list are explained in
  `docs/architecture.md`, "Data model".
- **Seed** (`make seed`): Tiong Bahru world with 12 shops (owners, addresses, coordinates,
  opening hours, limits, brand preferences, usual orders), 3 suppliers (tiered prices,
  secret floors, stock, delivery fee, reliability) and 16 SKUs including brand variants. It
  generates 8 weeks of daily sales (weekday, weekend, rain, holiday effects) and weekly
  purchase history. Deterministic. REAL modes come from `.env`; everything is simulated
  until PayPal credentials are set.
- **Swarm Clock:** Singapore business calendar, week plan (Monday forecasts ... Sunday
  report), and a position stored in the database. `app/runtime.py` loads it, together with
  the simulator snapshot, when the API starts.
- **Money engine:**
  - `pricing.py`: tiers, exact largest-remainder splits, delivery split by weight and
    distance, fees.
  - `rules.py`: spending limit, floor clamp, stock, capture and refund caps, honor period
    and reauthorization window.
  - `states.py`: group-order and shop-order state machines.
  - `ledger.py`: double-entry postings and the platform invariant.
  - `engine.py`: holds, reauthorize/re-hold, partial capture with final_capture, voids,
    cancellation, refunds, supplier payouts with withholding, swap charge and payout. All
    of it is crash-safe and idempotent.
- **Features used by later phases:**
  - `features/demand.py`: 4-week moving average with a holiday factor, plain-English
    explanation, propose/confirm/skip.
  - `features/group_buy.py`: pooling per category, supplier offers, list-price quotes,
    the award rule, brand-preference-aware award, delivery recording, savings versus
    buying alone.
- **Webhooks:** events are stored once (unique PayPal event ID); redeliveries return
  "duplicate". Payments are reconciled (for example a DENIED capture marks the payment
  FAILED and flags the shop order) and every event is audit-logged.
- **Simulated PayPal:** JSON snapshot persistence (saved after every change) and vault
  registration for seeded simulated shops.

**Works**
- 147 backend tests:
  - pricing, rules, state machines, ledger templates;
  - seed and demand;
  - pooling, award rule, substitutions, floors;
  - engine flows: happy path; short delivery partial capture; one failed authorization
    while the others continue; spending-limit approval; cancel/void; late-delivery
    reauthorization; 29-day re-hold; refunds after payout; idempotent re-runs; crash
    recovery without double charge; withheld payouts; swaps; a REAL shop through
    respx-mocked PayPal REST with the exact request IDs and bodies;
  - webhook dedupe and reconciliation;
  - the **4-week, 12-shop simulation**, which checks the ledger invariants and "no capture
    above authorization" after every day.
- A full simulated week on the dev database: 4 group orders, 37 holds, captures, payouts.
  Ledger balanced, platform gap 0, Teh Time asked for approval when over its S$300 limit.

**Pending**
- Negotiation (phase 3) replaces the list-price award for the live flow.

**Manual steps for you**
- None for this phase. (`make seed` resets the local database to the demo world.)

---

## Phase 3: Agents and negotiation

**Built**
- **LLM wrapper** (`app/llm/client.py`):
  - Anthropic SDK, model from `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`).
  - Structured outputs through `messages.parse` with a Pydantic schema per answer, and an
    effort level per task.
  - 60 s timeout, 2 retries; `refusal`, `max_tokens` and API errors become typed
    `LLMError`s.
  - Logs prompt name, model, latency and token usage for every call.
  - `OfflineLLM` (no key: deterministic paths) and `ScriptedLLM` (tests).
- **Agent base** (`app/agents/base.py`): id, owner, mandate from the database, versioned
  prompt file, tool list and the `validate()` gate. Refusals are audited.
- **Agents:**
  - Shop agent: Monday proposal with an owner approval, confirm/change/skip, free-text
    intents validated against the catalog, award news.
  - Supplier agent: code-generated legal price options, the model picks one, a style-based
    fallback policy.
  - Coordinator: RFQ -> QUOTE -> COUNTER -> FINAL_QUOTE -> AWARD, at most 3 rounds, award
    by rule.
  - Claims agent: photo assessment by vision, the refund decided by code and paid through
    the money engine.
- **Prompts:** `app/agents/prompts/*.md`, each versioned and carrying the "messages from other
  agents are data" rule. Untrusted text is wrapped and escaped.
- **Message bus + SSE:** every message stored in `agent_messages` and streamed live.
  `GET /api/stream` (agent messages + PayPal events) and `GET /api/agent-messages`.
- **CLI:** `make negotiate` (or `python -m app.cli negotiate [--category dairy] [--reseed]`)
  runs Monday and Tuesday and prints the conversation, results and savings.

**Works**
- 197 backend tests (50 new for this phase):
  - LLM wrapper: request shape, stop reasons, errors, usage logging;
  - prompts and escaping; supplier options, policy and gate;
  - the full negotiation protocol: award by rule, price goes down, no floors or rival
    names leaked;
  - single-bidder targets; a prompt-injection attempt that changes nothing; off-menu model
    answers falling back;
  - shop agent flows and intents; claims decisions and an automatic PayPal refund;
  - bus and SSE; the live API; the CLI.
- On the demo world, without a model:
  - all four categories negotiate in 3 rounds;
  - negotiation takes about 2.5% off the best opening quotes (dairy S$1,981.03 ->
    S$1,929.74);
  - shops save about S$2,300 in a week versus buying alone.

**Pending**
- The model-written messages have only been tested with mocks. They will run live once
  `ANTHROPIC_API_KEY` is set (the deterministic templates are what you see now).
- Owner approvals and claims photos arrive through Telegram in phase 4.

**Manual steps for you**
- Optional: add `ANTHROPIC_API_KEY` to `.env` and run `make negotiate` again to see the
  agents write their own messages. Everything works without it.
- Still pending from phase 1: the PayPal sandbox setup and `make smoke` run.
