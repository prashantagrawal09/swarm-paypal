# Devpost submission text

Draft for the Devpost form. Paste each section into the matching field, then add the hosted
URL, the repository URL and the video link. Numbers are from the demo week (always the week
of 12 October 2026) and match the README and the demo script.

Before submitting, check two things against what is actually deployed:

- "Honest about what is real" says four shops, three suppliers and the platform use the
  real sandbox. That is true once `docs/paypal-setup.md` is done and `REAL_SHOP_CODES` lists
  four shops. Change the sentence if you connect fewer.
- The test counts, if tests were added since.

---

## Project name

Swarm

## Tagline

Small shops buy alone and pay retail. Swarm lets them buy together and pay like a chain.

## Inspiration

A café in Tiong Bahru buys about 25 litres of milk a week and pays the top price for it.
Eleven other cafés, bakeries and hawker stalls on the same streets do the same, from the
same few suppliers. Together they buy almost 300 litres, which is a chain's order and a
chain's price. They don't get that price because nobody has time to coordinate twelve
owners, argue with suppliers, split a delivery fee fairly, or chase a refund when two
crates don't arrive.

That is work an agent can do. The hard part is trust: an owner will only let software
order for them if their money is safe. So the idea became: give every shop an agent, and
let PayPal be what makes it safe.

## What it does

Every shop gets its own agent. Over one week:

- **Monday.** Each shop's agent proposes next week's order from the last four weeks,
  adjusted for the weather forecast, and tells the owner why on Telegram. The owner taps
  Approve, or replies "less milk".
- **Tuesday.** Twelve orders become one. A coordinator agent negotiates with three supplier
  agents over three rounds, telling each one only the best competing price.
- **Wednesday.** PayPal places a hold on each shop's share. The money is reserved, not
  taken, and never above the owner's weekly limit without asking.
- **Thursday.** The delivery arrives. A shop that got 34 of 38 litres is charged for 34;
  the rest of its hold is released. The supplier's invoice is checked line by line against
  the deal; an overcharge of S$69.00 is caught and the invoice is rejected before anyone
  pays it. The corrected invoice is paid by PayPal Payouts.
- **Friday and Saturday.** A café's milk that would expire on Sunday is sold to a neighbour
  at a discount. A stall that runs out of eggs borrows a tray from a shop a minute's walk
  away, paid on the spot.
- **Sunday.** Every owner gets a savings report.

In the demo week, twelve shops save about S$2,340 (32% on dairy), keep 8.4 kg of food out
of the bin, and it takes 94 PayPal calls. The ledger balances to the cent.

The watch page replays the whole week as a one-minute film, and the live board shows all
of it as it happens: agent messages and money fly between the
shops, the suppliers and the coordinator on a map of the neighbourhood, and a narrator says
in one sentence what just happened.

## How I built it

**PayPal does the trusting.** Each capability does the job it was built for:

| Capability | Used for |
| --- | --- |
| Vault (save PayPal for future use) | One approval, then the agent can place weekly holds without the owner logging in |
| Orders: authorize | Money is held when a deal is agreed, not taken |
| Payments: partial capture with `final_capture` | Shops pay only for what arrived |
| Void and reauthorize | Cancelled orders release every hold; old holds are refreshed before capture |
| Refunds | Damage claims and short deliveries go back to the original payment |
| Invoicing (through the PayPal Agent Toolkit) | Supplier agents bill through PayPal; Swarm checks every line before paying |
| Payouts | Suppliers are paid minus a 2% fee; neighbours are paid for surplus |
| Webhooks | Verified events keep Swarm's books in step with PayPal |

**The agents suggest; the code decides.** A language model writes the messages, reads the
owners' replies and picks between options that code has already checked. It never sets an
amount. Prices, holds, captures, refunds and payouts are computed by a money engine with
state machines, idempotency keys on every PayPal call and a double-entry ledger. What one
agent says to another is treated as untrusted data, and every agent action passes a mandate
check first. Without a model key, every agent falls back to a deterministic policy, so the
demo never depends on a model call. You can see this for yourself: click any quote or award
in the conversation and the site shows the options code priced, who chose among them, and
the rules the choice passed before it was sent.

**Stack.** Python, FastAPI, PostgreSQL and SQLAlchemy on the back; Next.js, TypeScript,
Tailwind and AG Grid on the front, with live updates over Server-Sent Events. Telegram for
the owners. Hosted on Render. 331 backend tests (including four simulated weeks that must
keep the ledger balanced) and 77 frontend tests.

**Honest about what is real.** Four shops, the three suppliers and the platform use the
real PayPal sandbox. The other eight shops run on a simulator that follows the same rules
(capture limits, the three-day honour period, refund limits, idempotent replays). Every
account is labelled REAL or Simulated wherever it appears.

## Challenges

- **Paying for what arrived, not what was ordered.** A hold has to be captured for less
  than it was placed for, exactly once, even if the request is retried. That meant a
  payment step that records its intent first, calls PayPal with a stable request ID, and
  commits the result, the order's status and the ledger entries together.
- **Keeping the model away from the money.** The supplier agents negotiate, but the model
  only chooses from a menu of prices that code built from the supplier's private floor.
- **Splitting a delivery fee fairly.** Twelve shops share one delivery. The split is by
  weight and distance, in whole cents, and has to add up exactly.
- **Making a week watchable.** The week runs on a controllable clock, and everything the
  agents say and PayPal does is recorded in order. The watch page plays that recording back
  with the same code that draws the live board, so a judge can watch a week in about a
  minute without resetting it for anyone else.

## What I'm proud of

- An overcharged invoice is caught and rejected before any money moves, and the page shows
  exactly why.
- The money-flow diagram: every cent the shops were charged, through PayPal, to suppliers,
  neighbours, refunds and the fee. It always adds up, and a test proves it.
- Owners need about a minute a week, on a phone, with buttons.
- You can replay the whole week in a minute, as many people at once as like, because every
  message and payment is recorded as it happens.
- "The model can't set a price" is something you can check: each quote shows the options
  code priced, who picked one, and the rules the pick passed.

## What I learned

Agents are easy to make talk and hard to make safe. The useful split was strict: language
for people, code for money, and PayPal's own primitives (authorize, capture, void, refund,
payout) as the only way money can move.

## What's next

- PayPal multiparty payments, so funds go straight to suppliers and the fee is taken
  automatically.
- Cross-border settlement in MYR for the Malaysian supplier.
- Real point-of-sale data instead of generated sales history, and a live weather forecast.
- Reverse auctions, group service deals (pest control, cleaning) and supplier report cards.

## Built with

PayPal REST APIs (Orders v2, Payments v2, Payouts, Invoicing, Webhooks), PayPal Agent
Toolkit, Anthropic API, Python, FastAPI, PostgreSQL, SQLAlchemy, Next.js, React, TypeScript,
Tailwind CSS, AG Grid, Telegram Bot API, Render.

## Try it

1. Open the hosted URL and press **Watch a week run**: the recorded week plays back in
   about a minute (space pauses, arrow keys jump between days). No key or login is needed.
   (To let judges run or reset the week themselves when `DEMO_PANEL_KEY` is set, also give
   them `.../demo#key=YOUR-KEY`.)
2. Open **Demo panel** to change what goes wrong (a short delivery, an overcharged invoice)
   and to play any shop owner on their phone.
3. Open **Money** afterwards to see where every cent went.
