# Demo script (3 minutes)

Two windows side by side: **left** the live board (`/live`), **right** the demo panel
(`/demo`) with the owner's phone set to **Café Mei**. Optional third window: the PayPal
sandbox dashboard (Activity) for the REAL accounts.

Before recording: **Reset** in the demo panel. The clock goes to Monday 08:00.

Numbers below are from the seeded demo world without a language model. With
`ANTHROPIC_API_KEY` set, the agents word their messages differently, but the amounts are
the same: code computes every amount.

| Time | Do | Say |
|---|---|---|
| 0:00 | Landing page | "Twelve small food shops on one street in Tiong Bahru each buy milk alone and pay the top price. Swarm gives each of them an AI agent, and the agents buy together like a chain. Every hold, payment, refund and payout goes through PayPal." |
| 0:15 | Live board | "Twelve shops and three suppliers, each with an agent. The badges say honestly which accounts make real PayPal sandbox calls and which are simulated." |
| 0:25 | Demo panel → **Next: Monday: forecasts** | "Monday morning, each shop's agent proposes next week's order from the last four weeks. This week it expects rain Thursday to Saturday, so it orders a little less, and it says why." Point at the phone: "Next week you'll need about … rain on Thursday, Friday and Saturday expected, so about 8% less." Simulated owners answer for themselves; a REAL owner taps **Approve** in Telegram. |
| 0:45 | **Next: Tuesday: negotiation** (watch the live board) | "Twelve orders become one: 280 litres of milk instead of twelve small orders. The coordinator asks three supplier agents for quotes, tells each one the best competing price, and runs three rounds." Point at the **Negotiation** chart, then the **Price ladder**: "One shop alone pays S$2.45 a litre; twelve shops together reach the bottom tier, and negotiation takes it lower still. Dairy alone saves S$855." |
| 1:10 | **Next: Wednesday: PayPal holds** | "Now PayPal authorizes each shop's share. The money is held, not taken." PayPal feed: **Money held** rows with REAL / SIM badges. If showing the sandbox dashboard: the authorizations appear there. |
| 1:25 | **Next: Thursday: delivery** | "Delivery day. Café Mei ordered 38 litres but only 34 arrived." Phone: the owner replied "Only 34 L milk arrived". "So PayPal captures only what arrived, with final capture, and the rest of the hold is released automatically." Phone: **Charged S$133.33 … S$7.81 released back to you.** |
| 1:50 | **Next: Thursday: settlement** | "Johor Farm's agent invoices through PayPal Invoicing, but it charges S$2.11 a litre for milk instead of the agreed S$1.86. Swarm's coordinator checks every line, rejects it (overcharge S$69.00) and asks for a corrected invoice." Show the rejected and then approved invoice on the Money page or the group order. "Only the corrected invoice gets paid, by PayPal Payouts, minus Swarm's 2% fee." |
| 2:15 | **Next: Friday: surplus swap** | "Café Mei has 8 litres of milk expiring Sunday. Its agent offers it to neighbours who are running low, 35% off. Brew Lab takes it: Brew Lab is charged, Café Mei is paid out, and 8.4 kg of food stays out of the bin." The map draws the swap arc. |
| 2:30 | **Next: Saturday: emergency** | "Kopi Corner runs out of eggs on a Saturday morning. Its agent asks shops within 500 metres; Little Pasta says yes first. Instant payment, pickup instructions, sorted in seconds." Neighbours card: **sorted in …**. |
| 2:45 | **Next: Sunday: savings report** | Live board hero: "This week the street saved about S$2,340, 94 PayPal calls, and the books balance to the cent. The agents suggested; the code decided every amount." |
| 3:00 | End on the live board | |

## Shortcut

**Run the rest of the week** plays every remaining step, paced so the board can be followed
(about 2 minutes). Use it for a hands-off recording, or for judges trying it themselves.

## Surprises (demo panel → Surprises this week)

Each is armed for its day and can be changed before running:

| Card | Default | What the judge sees |
|---|---|---|
| Short delivery | Café Mei, milk, 90% delivered | A partial capture and a smaller charge |
| Overcharged invoice | Dairy, milk, +25¢ per litre | A rejected invoice, a corrected one, then the payout |
| Supplier flash deal | Johor Farm Fresh lettuce, 30 kg, 35% off (clamped to the supplier's floor) | Two shops' agents buy it within their owners' rules |
| Surplus stock | Café Mei, 8 L milk, 2 days left | **Post it now** offers it straight away |
| Emergency borrow | Kopi Corner, 1 tray of eggs | **Ask the neighbours now** runs it straight away |

## If something goes wrong

- The board says **Connecting**: the API is waking up (free hosting). Wait a minute.
- A step fails: the demo panel shows the error. **Reset** and start again; nothing outside
  the sandbox is touched.
- A REAL hold fails because a sandbox wallet isn't connected: open
  `/connect/<shop>` and approve, or remove the shop from `REAL_SHOP_CODES`.
