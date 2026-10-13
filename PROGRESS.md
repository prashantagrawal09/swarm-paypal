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
- 248 backend tests and 39 new frontend unit tests (Vitest: story captions, money-flow
  layout and conservation, map geometry, flights, search). Both run in `make check` and CI.
- `next build` is clean. Checked in headless Chrome at desktop and phone widths, light and
  dark, with no console errors.
- `docs/devpost.md`: the Devpost submission text, ready to paste.
- A full paced week takes about 75 seconds. `docs/screenshots/week.gif` is a recording of
  one (3.9 MB), now at the top of the README.

**Manual steps for you**
- Unchanged from phase 8: PayPal sandbox and `make smoke`, push, Render, video.

## PayPal setup helper

Setting up the sandbox by hand-editing `.env` was the step most likely to go wrong, so it is
now a guided command.

**Built**
- `make paypal-setup` (`backend/scripts/paypal_setup.py`): asks for each sandbox value in
  turn (Secrets hidden), tests every pair of keys with PayPal's sandbox token endpoint before
  saving, saves as it goes, and can be re-run (Enter keeps a value). It creates `.env` from
  `.env.example` with a generated `SECRET_KEY`, readable only by its owner.
- It sets `REAL_SHOP_CODES` to exactly the shops that have a buyer account, so a first setup
  with one shop doesn't leave three "real" shops without a wallet.
- `make paypal-check`: the same report without questions (which apps' keys work, which shops
  have a buyer and a saved PayPal, what to do next). Keys are never printed.
- `make smoke` now writes the PayPal it saved to that shop's `PAYPAL_SHOP_<CODE>_VAULT_ID`
  when the buyer who approved is one of the shops' owners, so no ID has to be copied by hand.
- `docs/paypal-setup.md` rewritten click by click for someone who has never used the
  Developer Dashboard, with direct links and a troubleshooting table.

**Not verified yet**
- The report's "Vault / Payouts / Invoicing on" line is read from the permissions on the
  app's token. It is a hint (worded as one) until it has been seen against a real sandbox
  app; `make smoke` is what proves each feature.

**Works**
- 13 new tests: `.env` edits keep comments and order, rejected keys are never saved, the
  wizard's retry, re-run and skip paths, and the smoke-test wallet only goes to the shop
  whose owner approved it.

**Fixed along the way**
- **Reset wiped real connections.** The demo panel's Reset reseeds every table, which also
  dropped an owner's saved PayPal (when it was connected in the app rather than set in
  `.env`) and every Telegram link. On the hosted demo a second run would have failed those
  shops' holds. Reset now carries both across; `make seed` is still the clean wipe.

## Deploy rehearsal

Ran Render's own build and start commands locally, from a clean `git archive` checkout into
an empty database, with production settings and a demo key, to find deploy problems before
the real deploy.

**Works**
- API: `pip install`, `alembic upgrade head` on an empty database, auto-seed, `/health`.
- Web: `npm ci`, `next build`, `next start`; every page answers.
- Guards: demo and owner endpoints answer 401 without the key, CORS allows only the web
  app's origin.
- A full paced week on the production build, started from **Watch a week run**.

**Fixed along the way**
- **The web build could fail on Render.** TypeScript and Tailwind are dev dependencies, and
  `npm ci` skips those when `NODE_ENV=production`. The build command is now
  `npm ci --include=dev`.
- **Two copies of the app.** `pip install .` put a second copy of the backend in
  site-packages without the seed data. It only worked because the server happens to import
  from the working directory. The build now installs it editable, so there is one copy.
- **A locked demo was a dead end.** With `DEMO_PANEL_KEY` set, **Watch a week run** ended at
  "open the demo panel". The live board now asks for the key in place and then runs what was
  asked. A link can also carry the key after a `#` (`/live?play=1#key=...`), which never
  reaches a server and is removed from the address bar.
- **A sleeping server looked like a broken product.** On Render's free plan the API takes
  about a minute to wake. Until it answered, the home page showed "S$0 saved", the live board
  told visitors to run `make backend`, and other pages said "Loading..." indefinitely. Every
  data page now shows a "Waking the demo server" screen with progress and carries on by
  itself; the home page keeps its story and says its numbers are on the way. On a laptop the
  same screen gives the developer hint instead.
- Page titles no longer wait on a sleeping API (2.5 s limit on the server-side name lookup).
- `docs/deploy.md` now covers what Render's free plan does to a demo: services sleep, the
  free database expires after 30 days, and the 750 shared hours rule out a keep-awake pinger.

## Watch page: the week as a film

The demo depended on someone pressing Run, and a second visitor could only watch by
resetting it for everyone. Now every run is recorded and anyone can play it back.

**Built**
- **A recording of the live stream.** Every agent message and PayPal event is written to a
  new `stream_events` table in the order it was sent (`app/agents/recorder.py`, migration
  `5c7c62089217`). `GET /api/timeline` returns a week of it (about 200 KB, 31 KB gzipped;
  JSON responses are now compressed, the event stream is not).
- **`/watch`.** A dark, full-window stage: the swarm map, a title card as each day begins,
  one sentence about what is happening, a tally (saved, held, charged, paid out, released,
  PayPal calls), the negotiation with each supplier's price falling round by round, and a
  closing summary of the week. Space pauses, the arrow keys jump between days, 1/2/3 set
  the speed, F is full screen. It works at phone width.
- **Replay, live, or start.** A finished week is replayed from the recording: each visitor
  gets their own showing, nothing is reset and PayPal isn't called again. A week that is
  running is followed live. A week nobody has run offers to run it. The home page's **Watch
  a week run** now goes here.
- **Reconnecting browsers catch up.** Stream events carry their position as the SSE `id`.
  A browser that reconnects sends `Last-Event-ID` and first gets what it missed, so a
  dropped connection no longer loses events on the live board either.
- **One step function for the stream.** The live layer's bookkeeping moved out of a React
  provider into a pure function (`lib/stream-state.ts`), used by both the live connection
  and the replay. The replay's totals are worked out from the events alone
  (`lib/world-state.ts`).

**Works**
- A test replays a real recorded week and checks the event-derived totals against the
  server's own books at the end of every step: charged, paid out, refunded, held and the
  number of PayPal calls all match to the cent.
- Backend: the recorder (ordering, weeks, pruning old weeks, failure never stops the week),
  catch-up without duplicates, the timeline endpoint, reset clears the recording.
- Checked in headless Chrome: replay at 1×, 2× and 4×, a live run started from
  `/watch?play=1`, the not-started state, the closing summary, and a phone-sized window.

**Fixed along the way**
- A flash-deal event didn't say what the supplier was actually paid (the amount less the
  fee), so anything adding up payouts from events was 96 cents out. It now carries
  `payout_cents`.
- Each finished step's event now carries the week's totals at that moment.

**Decisions**
- Events are recorded through their own short transaction, not the caller's, so recording
  can neither commit half-finished work nor be lost with it. If recording fails, the week
  carries on and the event is still sent live.
- A finished recording is frozen in the visitor's browser: someone else resetting the demo
  does not interrupt a replay.

## Home page: two things to try

**Built**
- **Buying together.** A slider for how many shops order together. The price per litre
  steps down the supplier's own price list (S$2.45 alone, S$2.15 from three shops, S$1.96
  from nine), with the pooled order's position marked on the list and the weekly saving
  beside it.
- **Paying for what arrives.** A slider for how much of an order turns up. The hold splits
  into what is charged and what is released, with the three PayPal calls behind it
  (authorize, final capture, remainder released).
- Both play themselves once when scrolled into view, then wait for the visitor.

**Decisions**
- The page computes nothing. `GET /api/explain` (`app/features/explain.py`) builds both
  tables with `app.money.pricing`, the functions the week itself runs on, from the street's
  usual milk order. Tests check every row against those functions.
- The README now opens with a recording of the watch page (`docs/screenshots/watch.gif`,
  4.3 MB) in place of the older live-board recording, with new watch-page and home-page
  screenshots.

## Inspector: how was this decided?

"Agents suggest, code decides" was a claim in the README. Now it is something you can click.

**Built**
- **Decision records.** When a supplier's agent quotes, the server keeps the options code
  priced, which one was chosen, whether the language model or the built-in policy chose it,
  and the rules the choice passed (`Agent.decided`, stored in the audit log next to the
  message's ID). The coordinator's award keeps the rule, the final quotes in order and who
  declined.
- **`GET /api/agent-messages/{id}/decision`** returns the record.
- **The inspector.** **How was this decided?** under a message opens a side panel: the
  message, the three steps of the decision (options, choice, checks), and the numbers it
  carried. Counter-offers show the one thing the supplier was told (the price to beat);
  invoice messages show the line-by-line check; charges show captured and released.
- Order pages now load their whole conversation from the server. Before, they only showed
  what was still in the browser's recent messages, so an order opened later looked empty.
  The live feed keeps a full week of messages, so its Negotiation filter reaches back to
  Tuesday.

**Decisions**
- The record goes to the audit log, not into the message. A quote's payload is read by the
  other side of the negotiation, and a supplier's options (down to its floor) are its own
  business. The API shows them in demo mode, with a note saying so, and leaves them out
  otherwise.
- The gate now reports which rules it checked (`Verdict.checked`), so the record lists the
  rules that actually ran, not a description of them.

**Works**
- Tests: every quote and award in a negotiation has a record; the option sent is exactly the
  chosen one; the message itself never carries the options; a model's choice is recorded as
  the model's; the options are hidden outside demo mode.

## PayPal, capability by capability

**Built**
- A section on the Money page listing each PayPal capability Swarm uses (Vault, authorize,
  capture, void, reauthorize, refunds, Payouts, Invoicing, webhooks): what it is used for,
  the REST call behind it, and the completed calls so far, split into real sandbox calls and
  simulated ones, with the amount moved and the latest PayPal ID
  (`GET /api/paypal-usage`, `app/features/paypal_usage.py`).
- A capability with nothing against it says so ("Not needed yet this week") instead of
  being left off.

**Works**
- A test runs a whole week and checks that every completed PayPal call is counted in exactly
  one row, and that each row's count and amount equal the payments table.

**Fixed along the way**
- **A photo claim could refund the wrong product.** A photo sent without first pressing a
  claim button was filed against whichever order had been charged last. "2 trays of eggs
  arrived cracked" was matched to the packaging order and refunded S$22.86 for something
  else. It is now filed against the newest delivery that contains the product the owner
  named (S$15.50 for two trays of eggs), with a test.

**Known gap**
- The scripted week has no damage claim, so the default demo never issues a refund, never
  voids a hold and never needs to reauthorize one; the table shows all three as not needed.
  `docs/demo-script.md` has the steps to show a refund by hand. I did not script one into
  the week: without a model key a claim has to be approved by a person, and a scripted
  approval of a claim nobody looked at would not be an honest demonstration.

## Second deploy rehearsal

After the changes above (a new migration, stream recording, compressed responses, three new
endpoints), I ran Render's build and start commands again from a clean checkout into an
empty database, in production mode with a demo key.

**Works**
- The new migration applies on an empty database; the API seeds itself and reports healthy.
- A week run through the API ends on the documented numbers (S$2,338.85 saved, 94 PayPal
  calls, books balanced), with 425 events recorded.
- `/watch` on the production web build replays that week to its closing summary without a
  demo key in the browser. Starting, stepping or resetting a week still answers 401 without
  one.
- The timeline is 31 KB compressed; a reconnect with `Last-Event-ID` gets exactly the
  events it missed; the worked examples, the capability table and the decision records all
  answer.

## Interface pass 3

Started from a full-page audit of every page at desktop and phone width.

**Built**
- **A shop's week, step by step** (shop page): what the agent did each day and what happened
  to the money, in the shop's own terms. "34 of 38 L milk arrived, so PayPal charged
  S$506.60 and released S$7.81", with the hold drawn as one bar split into charged and
  released. Built by a pure function from what the page already loads
  (`frontend/lib/shop-week.ts`, tested).
- The live board's two columns are now about the same height (neighbour activity moved
  under the PayPal feed), and the conversation opens on agents talking to each other; what
  owners and their own agents say is under **Owners**.

**Fixed along the way**
- **Flash deal times were in the wrong time zone.** "Until 14:00" was the UTC hour; the deal
  runs until 22:00 in Singapore. Messages now use Singapore time.
- **A flash deal stayed "Open" for days after it ended.** The API now reports a deal past
  its time as ended.

**Also built in this pass**
- **A third idea on the home page: an agent can't make up a price.** It shows a real quote
  decision from this week's negotiation: the options code priced (hover one to see what it
  would have meant), who picked, and the checks the pick passed, with a link to the
  conversation. `GET /api/explain` now returns it once a negotiation has happened; outside
  demo mode it is left out, because a supplier's options are private.
- **Watch page, for recording:** while the week plays, the controls and the cursor fade
  after a few seconds without input and come back on any movement. `?` lists the keyboard
  shortcuts.
- **A link preview image** (`app/opengraph-image.tsx`) and Open Graph / Twitter metadata, so
  a shared link shows the headline and the swarm instead of a bare URL. The site's address
  comes from `NEXT_PUBLIC_SITE_URL`, or `RENDER_EXTERNAL_URL` on Render.

## Accessibility audit

Ran axe-core (WCAG 2.1 A/AA and best practices) over 11 pages, 4 overlay states and 6
phone-sized pages, each in light and dark: 42 checks.

**Found and fixed**
- **Text too faint to read** on the watch page: older lines in "What the agents are saying"
  were faded to as little as 2.4:1 contrast. They now stay at full contrast; only the very
  top edge fades as lines scroll out.
- **The map and the money-flow diagram were announced as single pictures** while containing
  things you can tab to. They are now groups; the decorative map on the home page is still
  a picture.
- **Scrolling lists couldn't be reached from the keyboard** (the two live feeds and the demo
  panel's log). They can now be focused and scrolled.
- The live board had no page heading; the order page skipped a heading level; a table
  column had an empty header; the inspector panel's header and footer were read as the
  page's own banner and footer.
- People who ask their system for reduced motion now get fades instead of movement
  everywhere (`MotionConfig reducedMotion="user"`), and the watch page pauses the week while
  its shortcut list is open.

**Built**
- `make a11y` (`frontend/scripts/a11y.mjs`): the same audit, repeatable. It needs both
  servers running and a week run, and uses the Chrome already on the machine. All 42 checks
  pass.

**Not covered**
- This is an automated audit. It cannot judge whether the reading order makes sense or how
  the pages sound in a screen reader; nobody has tested with one.

**Also in this pass**
- **Download as CSV** under the PayPal activity, orders and quotes tables, with amounts in
  dollars and names instead of internal IDs.
- **The watch page says what was real.** Its tally and closing summary now state how many
  PayPal calls went to the real sandbox and how many were simulated, counted from the events
  themselves and checked against the server at every step.
- On the watch page only the buttons fade while the week plays; the day strip stays, so a
  recording still shows where in the week it is. The README GIF and the watch, shop and
  home-page screenshots were retaken.
- The order page's conversation stays in view while the page scrolls and opens from its
  first message.

**Checked**
- The whole backend suite and the frontend suite pass after everything above.
- **The weeks behind each forecast.** The shop page's forecast list now draws the last four
  weeks beside each number (grey bars) with this week's order (dark bar), so "based on your
  last four weeks, a little less for the rain" is something you can see. The forecast API
  returns those weeks.
- **Supplier page: how it competed this week.** For each group order the supplier quoted
  for, its landed price round by round against the others (drawn in front, rivals stepped
  back), with whether it won and by how much it lost.
- **The inspector opens from the watch page.** "How was this decided?" under a quote or
  award in the watch page's conversation pauses the week, opens the panel in the stage's
  dark theme, and resumes when it closes.
- `make a11y` still passes all 42 checks after these additions.

## Weekly statement

**Built**
- **A printable statement for each shop** (`/shop/<code>/statement`, linked from the shop
  page): what it bought with the street, order by order; its share of each delivery; what
  PayPal held, charged and released; the PayPal IDs; what it sold to or borrowed from
  neighbours; and how the week's saving adds up. **Print or save as PDF** gives a clean
  page: no site chrome, and light on paper even when the site is in dark mode.
- On a phone each order line stacks instead of squeezing into a six-column table.

**Works**
- Each order's lines plus its delivery share equal exactly what PayPal charged for it
  (`frontend/lib/statement.ts`, tested with the demo week's numbers: S$63.24 + S$27.23 +
  S$38.75 + S$4.11 = S$133.33).
- Checked on screen, at phone width, and as a printed A4 page; `make a11y` now covers 46
  page states, all passing.

## A hero that moves

**Built**
- **The home page's map replays the week on a loop.** Once a week has been recorded, the
  hero map plays it back at double speed, with a one-line caption of what is happening,
  rests on the finished week for a few seconds and starts again. The headline numbers stay
  the real, final ones. If the week is running right now the map is simply live.
- It stops when the map scrolls out of view, and does not start at all for visitors who ask
  their system for reduced motion.
- One focus ring for the whole site (keyboard users), in place of each browser's default.

**Decisions**
- The watch page and the home page share the replay staging (`frontend/lib/stage.ts`), so
  there is one way of turning a recording into what the map and captions show.

## A refund you can show, and the money held back for it

**Built**
- **Damage claim card** on the demo panel. **Add to Thursday** puts an owner's damage report
  into the week: it arrives after the delivery is charged and before the supplier is paid.
  **Report it now** files one at any time. Either way it comes without a photo, so the claims
  agent cannot judge it and a person decides under **Claims waiting for a person**.
- The queue says what is being asked for ("2 trays of eggs, damaged"), how much (S$15.50) and
  why a person has it. After **Refund**, it shows what PayPal did, with the refund ID.
- The live board shows **A claim is waiting for a person** with a link to decide it. The shop
  page's week tells it in order (charged, reported, refunded), the owner's phone shows their
  own report, and the supplier's invoice says what was held back and where it went.

**Fixed (money)**
- A claim with no photo, or with a photo nothing could read, used to carry S$0.00: the queue
  offered "Refund S$0.00" and nothing was held back from the supplier. Every open claim now
  carries what the owner claimed (never more than was delivered), and that is what is held.
- Money held back for a claim was never settled once the claim was decided. Now an upheld
  claim closes the order (the refund came out of the held money) and a rejected one pays the
  held amount to the supplier with a second payout, recorded on the PayPal invoice.

**Works**
- Scheduled claim, default data: Johor Farm Fresh is paid S$1,737.00 with S$15.50 held; after
  the refund, 95 PayPal calls, nothing owed either way, books balanced.
- 299 backend and 76 frontend tests pass. New ones cover: every way `decide` can leave a
  claim open has money at stake; held, refunded and rejected paths end with the supplier owed
  exactly nothing; the scripted week files no claim unless one is added.

**Decisions**
- The scripted week stays as it was (S$2,338.85 saved, 94 PayPal calls). The claim is opt-in,
  and **Reset** switches it off again.
- A claim upheld after the supplier was paid in full leaves the supplier owing Swarm the
  amount. The Money page says so; taking it off the next payout is not built (README,
  Limitations).

## Many tabs, and the page before anything has run

**Fixed**
- **With six tabs open, a seventh could not reach the server** and showed "The Swarm backend
  isn't answering". Each tab held its own live stream, and over plain HTTP (a local run) a
  browser allows six connections per server across all tabs. Now a tab nobody is looking at
  lets go of its stream and catches up, without replaying the animations, when it is shown
  again. A reset while a tab is hidden is noticed too: the tab starts over clean. On Render
  (HTTP/2) the limit did not apply, but hidden tabs now cost the server nothing there either.
- "No flash deals yet. One comes up on Saturday" and "Swaps and deals happen on Friday and
  Saturday" named the wrong day: the flash deal is Wednesday's.
- The empty agent feed said "Start the week from the demo panel" next to a Run the week button.

**Built**
- **A live board that explains itself before the week starts.** The two feeds list, day by
  day, what the agents will say and what PayPal will do; the group orders section shows the
  four orders about to open and what goes into each.
- **PayPal, capability by capability** says when each one comes up ("Thursday, when
  deliveries arrive") or what it would take ("Only when a claim is upheld"), in place of
  "Not needed yet this week".
- **Proper pages for things that aren't there**: an unknown shop, supplier or group order gets
  a heading, a sentence and a way back, in place of a dashed box.

**Works**
- Checked with nine tabs open at once (all load), with a tab hidden through Tuesday's
  negotiation (12 messages before, 62 after it came back), and with a reset while hidden.
- `make a11y` passes both with a week run and on a freshly reset demo.

