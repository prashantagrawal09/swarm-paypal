# Demo script (3 minutes)

## The easy recording: the watch page

`/watch` plays the whole week as a film on a dark stage: the map, each day's title, one
sentence about what is happening, and the money adding up, ending on a summary of the week.
It replays the recording of the last run, so you can record it as many times as you like
without resetting anything.

1. Run the week once (the first press of **Watch a week run** does this, or **Run the
   week** on the live board).
2. Open `/watch`, press `F` for full screen, and record. **Space** pauses, **←** and **→**
   jump between days, **1** / **2** / **3** set the speed (a full week is about 70 seconds
   at 1×), **R** starts again. Clicking a day in the strip along the top jumps straight to
   it, so a retake can start from Thursday.
3. Talk over it with the "Say" column below; the day titles tell you where you are.

To have a refund in the film, add the damage claim to Thursday before running the week (see
**Showing a refund**): the recording then shows the claim holding S$15.50 back from the
supplier's payout.

Keep as many tabs open as you like while recording. A tab you are not looking at lets go of
its live connection and catches up when you come back to it.

Use the live board (next section) when you want to show the detail: the owner's phone, the
price ladder, an invoice being rejected line by line.

## The detailed walkthrough: the live board

One window is enough: the **live board** (`/live`). It has its own **Run the week** and
**One step** buttons, and a narrator line that says in plain words what is happening. Open
the **demo panel** (`/demo`) in a second window if you want the owner's phone on screen, set
to **Café Mei**. Optional third window: the PayPal sandbox dashboard (Activity) for the REAL
accounts.

Before recording: press **Reset** in the demo panel (or **Run the week again** on a finished
board). The clock goes to Monday 08:00 of the demo week, which is always 12 October 2026,
so the numbers below are the same on any day.

What to point at on the live board:

- **The narrator** (top): one sentence for each thing that matters, as it happens.
- **The swarm map**: thin dark streaks are agent messages; thick glowing streaks are money
  (honey = held, green = charged, dark = paid out to a supplier, amber = released or
  refunded). Pins turn honey when money is held and green when the shop has been charged.
- **Negotiating now**: appears during Tuesday. Each supplier's dot slides left as its price
  falls.
- **Price ladder** (group order cards): the marker walks down the tiers as twelve orders
  become one.

Numbers below are from the seeded demo world without a language model. With
`ANTHROPIC_API_KEY` set, the agents word their messages differently, but the amounts are
the same: code computes every amount.

| Time | Do | Say |
|---|---|---|
| 0:00 | Landing page | "Twelve small food shops on one street in Tiong Bahru each buy milk alone and pay the top price. Swarm gives each of them an AI agent, and the agents buy together like a chain. Every hold, payment, refund and payout goes through PayPal." |
| 0:15 | Live board | "Twelve shops and three suppliers, each with an agent. The badges say honestly which accounts make real PayPal sandbox calls and which are simulated." |
| 0:25 | **One step** (Monday: forecasts) | "Monday morning, each shop's agent proposes next week's order from the last four weeks. This week it expects rain Thursday to Saturday, so it orders a little less, and it says why." Point at the phone: "Next week you'll need about … rain on Thursday, Friday and Saturday expected, so about 8% less." Simulated owners answer for themselves; a REAL owner taps **Approve** in Telegram. |
| 0:45 | **One step** (Tuesday: negotiation) | "Twelve orders become one: 280 litres of milk instead of twelve small orders. The coordinator asks three supplier agents for quotes, tells each one the best competing price, and runs three rounds." Point at **Negotiating now** (the dots sliding left), then the **Price ladder**: "One shop alone pays S$2.45 a litre; twelve shops together reach the bottom tier, and negotiation takes it lower still. Dairy alone saves S$855." |
| 1:10 | **One step** (Wednesday: PayPal holds) | "Now PayPal authorizes each shop's share. The money is held, not taken." Honey streaks fly from every shop to the coordinator and the pins turn honey. PayPal feed: **Money held** rows with REAL / SIM badges. If showing the sandbox dashboard: the authorizations appear there. |
| 1:25 | **One step** (Thursday: delivery) | "Delivery day. Café Mei ordered 38 litres but only 34 arrived." Phone: the owner replied "Only 34 L milk arrived". "So PayPal captures only what arrived, with final capture, and the rest of the hold is released automatically." Phone: **Charged S$133.33 … S$7.81 released back to you.** |
| 1:50 | **One step** (Thursday: settlement) | "Johor Farm's agent invoices through PayPal Invoicing, but it charges S$2.11 a litre for milk instead of the agreed S$1.86. Swarm's coordinator checks every line, rejects it (overcharge S$69.00) and asks for a corrected invoice." The narrator turns red: "Invoice rejected: Johor Farm Fresh overcharged S$69.00." Then green streaks (charges) and dark streaks (payouts) fly. "Only the corrected invoice gets paid, by PayPal Payouts, minus Swarm's 2% fee." |
| 2:15 | **One step** (Friday: surplus swap) | "Café Mei has 8 litres of milk expiring Sunday. Its agent offers it to neighbours who are running low, 35% off. Brew Lab takes it: Brew Lab is charged, Café Mei is paid out, and 8.4 kg of food stays out of the bin." The map draws the swap arc. |
| 2:30 | **One step** (Saturday: emergency) | "Kopi Corner runs out of eggs on a Saturday morning. Its agent asks shops within 500 metres; Little Pasta says yes first. Instant payment, pickup instructions, sorted in seconds." Neighbours card: **sorted in …**. |
| 2:45 | **One step** (Sunday: savings report) | Live board hero: "This week the street saved about S$2,340, 94 PayPal calls, and the books balance to the cent. The agents suggested; the code decided every amount." |
| 3:00 | End on the live board | |

## Shortcut

**Run the week** plays every step, paced so the board can be followed (about 75 seconds).
The landing page's **Watch a week run** button opens the watch page (`/watch?play=1`): it
replays the recorded week, or runs it there and then if nobody has run it yet.

After the run, the **Money** page shows where every cent went as a flow diagram (shops →
PayPal → suppliers, neighbours, refunds, fee), and it always adds up.

## Showing that the agents can't set prices

Open a group order (for example **Dairy & eggs** from the live board) and, in **The
conversation**, press **How was this decided?** under a supplier's quote. The panel shows:

1. the options code priced from that supplier's price list and floor (hold, a small step
   down, just beat the best rival, a big step down, the floor);
2. who chose one: the language model, or the built-in policy when no model key is set;
3. the rules the choice passed before it was sent (nothing below the floor, enough stock,
   never higher than the last quote).

Under the **Awarded** message it shows the award rule, the final quotes in order, and that no
model was asked who should win. Say: "The model can only pick from a list that code has
already priced, and code checks the pick again before anything is sent."

## Showing a refund

The scripted week has no damage claim, so it never issues a refund. Three ways to show one:

**Inside the week (the best one for a video).** Before running the week, demo panel →
**Surprises this week** → **Damage claim** → **Add to Thursday**. During Thursday's
settlement Bakery Lim's owner reports 2 trays of eggs damaged, with no photo:

1. The claims agent can't judge it, so it tells the coordinator to hold S$15.50 (two trays at
   the agreed S$7.75) back from Johor Farm Fresh. The coordinator's payout message says
   "holding S$15.50 until open claims are settled", and the dairy order shows **Part settled**.
2. The live board shows **A claim is waiting for a person** → **Decide it**.
3. Under **Claims waiting for a person**, press **Refund S$15.50**. PayPal refunds the
   original payment out of the held money, the supplier is told it was upheld, the order
   becomes **Settled**, and the books still balance. Press **Reject** instead and the S$15.50
   is paid to the supplier by a second payout.

Say: "Swarm never pays a supplier for goods that are in dispute, and never refunds on an
agent's say-so when there is no evidence. A person decides; PayPal moves the money."

**Any time after Thursday.** Same card → **Report it now**, then **Refund S$15.50**. The
supplier has already been paid in full by then, so the Money page says plainly that the
supplier owes the S$15.50 back.

**With a photo.** Demo panel → **Be the owner** → pick **Bakery Lim** → press the camera
and send any photo. The agent asks what's wrong; answer `2 trays of eggs arrived cracked`
(or type that first and then send the photo). With `ANTHROPIC_API_KEY` set, the claims agent
looks at the photo and refunds a clear case by itself (up to S$50). Without a key, or if the
photo is unclear, the claim waits under **Claims waiting for a person**.

Afterwards **Money → PayPal, capability by capability** shows the refund call, and
**Shops → Bakery Lim** shows the report and the refund in the week's steps.

## Surprises (demo panel → Surprises this week)

Each is armed for its day and can be changed before running:

| Card | Default | What the judge sees |
|---|---|---|
| Short delivery | Café Mei, milk, 90% delivered | A partial capture and a smaller charge |
| Overcharged invoice | Dairy, milk, +25¢ per litre | A rejected invoice, a corrected one, then the payout |
| Supplier flash deal | Johor Farm Fresh lettuce, 30 kg, 35% off (clamped to the supplier's floor) | Two shops' agents buy it within their owners' rules |
| Surplus stock | Café Mei, 8 L milk, 2 days left | **Post it now** offers it straight away |
| Emergency borrow | Kopi Corner, 1 tray of eggs | **Ask the neighbours now** runs it straight away |
| Damage claim | Bakery Lim, 2 trays of eggs; off unless added | **Add to Thursday** holds that much back from the supplier until a person decides; **Report it now** files one on the spot |

## If something goes wrong

- The board says **Connecting**: the API is waking up (free hosting). Wait a minute.
- A step fails: the demo panel shows the error. **Reset** and start again; nothing outside
  the sandbox is touched.
- A REAL hold fails because a sandbox wallet isn't connected: open
  `/connect/<shop>` and approve, or remove the shop from `REAL_SHOP_CODES`.
