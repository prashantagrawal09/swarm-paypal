# Progress

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation | Done |
| 1 | Prove PayPal | Done (simulated); waiting on your sandbox run |
| 2 | Data model and money engine | Not started |
| 3 | Agents and negotiation | Not started |
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
