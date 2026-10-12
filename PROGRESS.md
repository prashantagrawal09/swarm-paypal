# Progress

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation | Done |
| 1 | Prove PayPal | Done (simulated); waiting on your sandbox run |
| 2 | Data model and money engine | Done |
| 3 | Agents and negotiation | Done |
| 4 | Telegram bot | Done (needs your bot token to go live) |
| 5 | Web app | Done |
| 6 | Hero features F2–F5 | Done (backend; UI in phase 5) |
| 7 | Supporting features and polish | Done |
| 8 | Deploy and submission | Ready to deploy (needs your Render and GitHub accounts) |
| + | Interface pass (beyond the spec) | Done |

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

---

## Phase 6 (backend) and phase 4: hero features, owner conversations, Telegram

Phase 6's backend was built before the phase 5 web app, so the UI could show every feature.

**Built**
- **F2, pay only for what arrived** (`features/delivery.py`):
  - Thursday dispatch messages with All arrived / Something's missing / Damaged buttons.
  - Owners type what came ("milk 30") and it's parsed into quantities.
  - Unconfirmed deliveries count as full; partial capture with `final_capture`; owners are
    told what was charged and what was released.
- **F3, invoice checker** (`features/invoice_checker.py`):
  - The supplier invoices the platform: PayPal Agent Toolkit for REAL suppliers, the
    simulator otherwise.
  - Code checks every line against the agreed prices, delivered quantities and delivery
    charge. A mismatch is rejected with the spec's wording ("Milk: charged S$2.30/L,
    agreed S$2.05/L, 290 L, overcharge S$72.50.").
  - The supplier cancels the bad invoice and reissues. The approved one is paid by Payout
    (holding back open claims) and the payment is recorded on the PayPal invoice.
  - `cancel_invoice` was added to every gateway.
- **F4, surplus swap**: price falls with days to expiry, never below the owner's minimum.
  Offered to up to three nearby shops that use the product and accept the brand. Buyer
  rule: at most 85% of its own price and within its limit. The buyer is held, the seller is
  paid on handover, and food saved is recorded.
- **F5, emergency borrow**: shops within 500 m that stock enough are asked; first yes wins.
  The price is the helper's cost +10%. Payment is instant, with pickup instructions and
  walking time. Time to sorted is measured.
- **Claims**: photo stored in Postgres (`/api/media/{id}`); the claims agent assesses it.
  The supplier's agent accepts clear claims up to S$100, otherwise the operator decides in
  the demo panel. Open claims are withheld from payouts.
- **F8, flash deals**: discount clamped to the supplier floor; one-tap offers to matching
  shops; instant purchase with the supplier paid at once (`engine.purchase_now`).
- **F9, over-limit approvals**: owners get Approve once / No buttons for holds, swaps and
  deals. The answer resumes exactly that step.
- **F7, savings**: per shop per week (group buys vs alone, swaps, flash deals, food saved,
  refunds) and platform totals; Sunday report to every owner.
- **Week runner** (`features/week.py`): 8 idempotent steps (Mon forecasts ... Sun report)
  with a demo scenario: short delivery, wrong-price invoice, flash deal, surplus,
  emergency. Simulated owners answer from their preferences; real owners answer on
  Telegram (no reply by Tuesday means the usual order).
- **Demo controls** (`demo/controls.py` + `/api/demo/*`): state, advance, run the whole week
  in the background (paced for viewers), injections, reset and reseed, operator claim
  decisions. Optional `DEMO_PANEL_KEY`.
- **PayPal connect** (`/api/connect/*`): S$1.00 check with "save PayPal", vault ID stored,
  check voided. The same flow works against the simulator with an in-app approval screen.
- **Owner conversations** (`owners/service.py`): one handler for buttons, typed answers,
  free text (via the shop agent) and photos, shared by Telegram and the web phone.
- **Telegram bot** (`telegram_bot/`), python-telegram-bot 22:
  - commands `/start <code>`, `/as <code>` and `/shops` (demo), `/report`, `/help`;
  - coloured inline buttons;
  - photos go to claims; voice notes are transcribed by faster-whisper when installed;
  - a notifier relays every owner message from the bus;
  - polling locally, webhook with a secret in production; runs inside the API process.
- **Read API** for the web app: overview, shops, suppliers (floors never exposed), group
  orders with price-ladder data, payments, ledger, swaps, invoices, claims, flash deals.
- **Production bits:**
  - a scheduler runs the week on real time when `DEMO_MODE=false`;
  - auto-seed on an empty database;
  - request IDs, JSON 500s and security headers;
  - payments now record their shop and supplier (migration).

**Works**
- 229 backend tests, including a full Monday-to-Sunday week.
- Live through the API: reset plus "Run full week" took about 2 minutes, with 307 agent
  messages streamed over SSE. The week saved shops S$2,327, S$144.58 of it from
  negotiation, rescued 8.4 kg of food and made 90 PayPal calls, with the books balanced.

**Manual steps for you**
- Optional: create a Telegram bot (`docs/telegram-setup.md`, 2 minutes) and put
  `TELEGRAM_BOT_TOKEN` in `.env`. Without it, use the web phone in the demo panel.

---

## Phase 5: Web app

**Built**
- **Design system** (`app/globals.css`, `components/ui.tsx`): light and dark tokens (system,
  light or dark, chosen in the header and applied before paint), a honey brand colour, and a
  validated categorical palette with one fixed colour per supplier, never by rank. Status
  colours always come with an icon and a word. Cards, pills, buttons and meters are shared.
- **Live data layer**:
  - One SSE connection for the whole app (`lib/live.tsx`) keeps agent messages and PayPal
    events, marks which shop just had activity, and revalidates every SWR query shortly
    after anything happens, so all the numbers agree.
  - Typed API client (`lib/api.ts`).
- **Live board** (`/live`):
  - the week's headline saving with a count-up, and stat tiles for PayPal calls, money
    held, charged, paid out, fee and the ledger check;
  - the eight-step week;
  - an SVG map of Tiong Bahru: shop pins coloured by where each shop's week stands, pulses
    when an agent talks, arcs for neighbour swaps;
  - group order cards with the price ladder (one shop alone vs. the pooled tier vs. the
    negotiated price) and the negotiation chart (landed price per supplier per round);
  - the agent conversation (filterable) and the PayPal feed (live events plus history,
    REAL/SIM badges).
- **Demo panel** (`/demo`):
  - next step, run the rest of the week, reset;
  - the five surprises with editable details, surplus and emergency also "now";
  - the owner's phone (same chat, buttons, text and photos as Telegram);
  - the operator's claims queue with the claims agent's assessment;
  - what the server runs with, and the panel log;
  - a prompt for `DEMO_PANEL_KEY` when the server asks for one.
- **Shops** (`/shops`, `/shop/[id]`):
  - savings and spend against the weekly limit;
  - alone vs. Swarm per category;
  - orders, PayPal activity, neighbour swaps and claims in AG Grid (themed from the same
    tokens);
  - owner decisions and what the agent knows (usual week, brand rules);
  - the owner's chat.
- **Suppliers** (`/suppliers`, `/supplier/[id]`): catalog and volume tiers (floors never
  shown), invoices with the coordinator's check (rejections spelled out), quotes and payouts.
- **Group order** (`/orders/[id]`): every product's ladder, the negotiation, each shop's
  hold / charge / refund and authorization ID, invoices and payouts, and the conversation.
- **Money** (`/money`): every PayPal payment (filter REAL / simulated), ledger balances with
  the invariant check, recent invoices, flash deals.
- **Connect PayPal** (`/connect/[shopId]`): explains the S$1.00 check, sends REAL shops to
  PayPal and finishes when they come back, and shows simulated shops a clearly labelled
  simulator approval.
- **Landing page**: the pitch, the week, the PayPal building blocks, the agents, with live
  numbers.
- Not-found and error pages, app icon, skip link, keyboard-reachable map pins, reduced motion
  respected, no sideways scrolling at phone width.

**Backend changes made for the UI**
- Owner links are signed (`app/security.py`, new `SECRET_KEY`):
  - Outside demo mode, `/start` needs an invite from `python -m app.cli invite <shop>`, so
    nobody can link a chat to a shop by guessing its code.
  - The connect API needs the owner's signed link (the bot's new `/connect` command hands
    it out), so nobody can attach their wallet to someone else's shop.
  - The web phone endpoints are demo-only (behind the demo guard).
- New rows are stamped with the Swarm Clock, so payments, approvals and invoices show demo-week
  times. Rows created in the same instant keep their creation order.
- Invoice events (sent, checked, cancelled) go on the live stream; `/api/products` lists
  products and SKUs; `/api/agent-messages` can return the latest messages.

**Works**
- 236 backend tests pass. eslint, tsc and `next build` are clean.
- Checked in the browser at desktop and phone widths, light and dark. Reset, then run the
  week: the board fills in live, pins go from held to charged, and the swaps draw their arcs.
  The week ends with S$2,327 saved, 90 PayPal calls and the books balanced. Connect PayPal
  completes end to end against the simulator.

**Manual steps for you**
- Set `SECRET_KEY` in `.env` before running with `DEMO_MODE=false`.

---

## Phase 7: Supporting features and polish

**Built**
- **F6, demand prediction with reasons**:
  - The 4-week average is now multiplied by a weather factor and a holiday factor, both
    from `seed/data/demand.json`.
  - Weather compares the coming week's outlook with the usual mix already in the history.
    Each trading day counts by how busy it normally is (weekday factors and the shop's
    weekend lift). A rainy day costs each shop its own rain factor, so a hawker stall drops
    more than the tea house, which sells more in the rain.
  - The demo week has rain forecast Thursday to Saturday.
  - Every forecast line explains itself ("About 13 L milk: your last 4 weeks averaged 14,
    minus 8% for rain on Thursday, Friday and Saturday").
  - The owner's Monday message carries one line on why ("Based on your last 4 weeks; rain
    on ... expected, so about 8% less. Shall I order that?"). With an API key, the shop
    agent's model writes that line from the same facts.
  - The shop page shows the week's forecast with each reason.
- **F8, flash deals that get taken**: a flash deal is judged as a mid-week top-up.
  Simulated owners buy when it is at least 20% under the single-unit price and no dearer
  than their group price. In the demo, two shops buy the lettuce. REAL owners still decide
  with a button.
- **Live board**: a "Neighbours and deals" card shows surplus swaps (food not wasted),
  emergency borrows (time to sorted) and flash deals (taken / available).
- **F7, F9 and F10** were already in place: savings reports in Telegram and on the shop page,
  spending-limit approvals with owner buttons, voice notes when faster-whisper is installed.

**Works**
- 239 backend tests pass, including weather weighting (rain on a busy Saturday costs more
  than on a quiet Monday) and the week test now checking that the flash deal sells.
- Demo week end to end: S$2,338.85 saved, 94 PayPal calls, 8.4 kg of food not wasted, books
  balanced.

**Manual steps for you**
- None new.

---

## Phase 8: Deploy and submission (prepared)

**Built**
- `render.yaml`:
  - Postgres 16, the API (migrations on start, health check, seeded on first start) and the
    web app, all on the free plan in Singapore;
  - every secret is either asked for once (`sync: false`) or generated (`SECRET_KEY`,
    `TELEGRAM_WEBHOOK_SECRET`).
- Hosting fixes:
  - `postgres://` URLs from hosts are switched to the psycopg driver;
  - Telegram webhook secrets are made Telegram-safe (Render's generated values contain
    `+/=`, which Telegram rejects);
  - the API logs any setting that is still unsafe for production at start.
- `docs/deploy.md`: Blueprint, wiring the two URLs, PayPal webhooks, REAL shops, Telegram,
  troubleshooting.
- `docs/demo-script.md`: the 3-minute video, step by step against the demo panel buttons,
  with the demo's actual numbers.
- Screenshots in `docs/screenshots/`: live board (light, dark, phone), demo panel, shop,
  supplier invoices, money. Taken from the running app.
- README:
  - what Swarm is and who it's for;
  - screenshots;
  - tools used (AG Grid, Render, Agent Toolkit, LLM);
  - Telegram and deploy setup;
  - the demo walkthrough;
  - more limitations.
- Architecture doc: live updates and who may act for a shop.
- Fix: the weekly report no longer calls emergency help "selling surplus".

**Section 12 checklist**
1. What Swarm is, who it's for, why it matters: README intro and "Why it matters".
2. Features with screenshots: done (a screen recording is still to come).
3. Architecture and agent diagrams (mermaid): README and `docs/architecture.md`.
4. "How Swarm uses PayPal" table with every capability and the Agent Toolkit actions.
5. "How Swarm uses AI": the agents, what the model decides vs. what code decides, safety rules.
6. Tools used: AG Grid, Render, PayPal Agent Toolkit, and the LLM line exactly as Rule 2.
7. Setup: PayPal sandbox (`docs/paypal-setup.md`), `.env`, docker-compose, migrations,
   seed, backend, frontend, bot, smoke test.
8. Demo walkthrough matching `docs/demo-script.md`.
9. Limitations and production path.
10. MIT license at the repo root.

**Works**
- 243 backend tests, eslint, tsc and `next build` all pass.

**Manual steps for you** (in this order)
1. PayPal sandbox setup and `make smoke` (`docs/paypal-setup.md`), so the REAL accounts
   are proven before they go on the hosted app.
2. Push to GitHub. `SWARM_SPEC.md` is your build brief; consider leaving it out of the
   public repo.
3. Render: New > Blueprint (`docs/deploy.md`), then wire the two URLs.
4. Put the hosted URL at the top of the README, record the video with
   `docs/demo-script.md`, and add it to the README and Devpost.
5. Optional: `ANTHROPIC_API_KEY` (agents write their own messages) and a Telegram bot.

---

## Interface pass (beyond the spec)

Everything here was built while waiting for the PayPal credentials and the deploy. No
spec item was changed; this makes the week easier to watch and understand.

**Built**
- **The swarm map** (`components/swarm-map.tsx`, replaces the plain shop map):
  - the three suppliers are depots along the top and the coordinator is a hub in the
    middle;
  - every agent message is a thin streak between the two agents involved;
  - every payment is a thick glowing streak: honey for holds, green for charges, dark for
    payouts, amber for releases and refunds;
  - pins change colour as money is held and then charged, and the hub shows how much is
    held right now;
  - reduced motion switches the streaks off.
- **The narrator** (`components/narrator.tsx`, `lib/story.ts`): one plain sentence for what is
  happening right now ("Invoice rejected: Johor Farm Fresh overcharged S$69.00."), with
  **Run the week** and **One step** on the live board itself. One window is now enough.
- **Negotiating now** (`components/negotiation-spotlight.tsx`): appears while a group order is
  being negotiated. One lane per supplier, opening and latest quote on a shared scale, the
  dots sliding left as prices fall, the winner marked at the award.
- **Price ladder that drops**: when a group order appears, its marker walks down the tiers
  from one shop's quantity to the pooled quantity ("1 shop: S$2.45" ... "12 shops: S$1.96").
  This is the spec's "price ladder dropping as orders pool".
- **Where the money went** (`/money`, `components/charts/money-flow.tsx`, `/api/money-flow`):
  a flow diagram from each shop's charges, through Swarm's PayPal balance, to suppliers,
  neighbours, refunds and the fee. The parts always add up to what was charged (tested).
- **Home page**: the live swarm map in the hero, a ticker of real agent messages, scroll
  reveals, and **Watch a week run**, which resets and plays the week in one click
  (`/live?play=1`).
- **Command palette** (`⌘K` / `Ctrl+K`): jump to any page, shop, supplier or group order, or
  switch theme.
- **Toasts** on every page but the live board for the big moments (short delivery, rejected
  invoice, refund, neighbour swap, week complete).
- Paced single steps: **One step** and the demo panel's **Next** now play at the same
  watchable pace as the full run (`POST /api/demo/advance?paced=true`, in the background).
- Loading skeletons, hover states, and no layout jump when the narrator's caption changes.

**Ready for a small server**
- Every shop's savings and committed spend are now read in three queries each instead of
  several per shop (`savings.week_reports`, `engine.committed_by_shop`; the per-shop rules
  call the same code, and a test checks they agree).
- The summaries the live board polls are computed once and shared between everyone
  watching until something happens (`app/api/readcache.py`, at most 3 seconds stale).
- Locally the overview went from 162 ms to 29 ms (8 ms shared) and the shop list from 75 ms
  to 16 ms. This matters on Render's free plan, where the same small process also runs the
  week.

**Accessibility**
- Muted and critical text now meet WCAG AA (4.5:1) on every surface in both themes; the
  brighter red is kept for marks only.
- The map's pins, the money-flow nodes and the command palette all work from the keyboard;
  reduced motion turns off flights, pulses and the ticker.

**Fixed along the way**
- **The demo week drifted with the real date.** The seed picked "next Monday from today",
  so after a few days the numbers no longer matched the README, the demo script or the
  weather outlook. The demo week is now fixed (`DEMO_WEEK`, default 12 October 2026).
- Group orders expose their negotiation's conversation ID from the start, so the board can
  follow a negotiation in progress.
- Status pills in the tables were stretched to the row height.
- The demo panel's surprise cards showed the wrong days (the invoice check is Thursday, the
  flash deal Wednesday, the surplus swap Friday).

**Works**
- 247 backend tests and 39 new frontend unit tests (Vitest: story captions, money-flow
  layout and conservation, map geometry, flights, search). Both run in `make check` and CI.
- `next build` is clean. Checked in headless Chrome at desktop and phone widths, light and
  dark, with no console errors.
- A full paced week takes about 75 seconds. `docs/screenshots/week.gif` is a recording of
  one (3.9 MB), now at the top of the README.

**Manual steps for you**
- Unchanged from phase 8: PayPal sandbox and `make smoke`, push, Render, video.
