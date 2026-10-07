# Telegram setup

Shop owners talk to their Swarm agent on Telegram. Without a bot token everything still works:
the demo panel has a web phone that shows each owner's chat and lets you press the same
buttons.

## 1. Create the bot (2 minutes)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a name (for example *Swarm Tiong Bahru*) and a username ending in `bot`.
3. Copy the token into `.env`:

   ```dotenv
   TELEGRAM_BOT_TOKEN=123456789:AA...
   ```

4. Restart the backend (`make backend`). The log says `Telegram bot running (polling)`.

Locally the bot uses long polling, so no public URL is needed. In production
(`PUBLIC_BACKEND_URL` starts with `https://`) it registers a webhook at `/telegram/webhook`
and checks `TELEGRAM_WEBHOOK_SECRET` on every call.

## 2. Link a chat to a shop

Send your bot:

```
/start cafe-mei
```

From then on you are Mei at Café Mei: the Monday order, award news, the delivery check,
swap offers, refunds and the Sunday report arrive in this chat with buttons.

With `DEMO_MODE=false` a plain shop code is refused: owners join with a signed invite,
so nobody can take over a shop by guessing its code. Make one with

```bash
cd backend && .venv/bin/python -m app.cli invite cafe-mei --bot YourSwarmBot
```

and send the owner the `t.me/...?start=...` link it prints (it needs `SECRET_KEY`, and
expires after 7 days). In the chat, `/connect` gives the owner a signed link to connect their
PayPal.

In demo mode one Telegram account can play several owners:

- `/shops` lists the shop codes.
- `/as bakery-lim` switches to another shop. Every shop you've switched to keeps sending
  its messages to this chat, labelled with the shop's name, and buttons always act for the
  shop the message came from.

## 3. Things to try

| You send | What happens |
|---|---|
| Tap **Approve** on Monday's message | Your order joins Tuesday's group buy |
| Tap **Change**, then `milk 40, eggs 0` | Quantities updated, then confirmed |
| `need extra oil this week` | This week's oil goes up (if the order isn't placed yet) |
| `8 L milk expiring Sunday` | Your agent offers it to neighbours at a discount |
| `Out of eggs, need 30 now` | Neighbours within 500 m are asked; first yes wins, instant payment |
| Tap **Something's missing**, then `milk 30` | You're only charged for 30 |
| Send a photo of damaged goods | The claims agent checks it; clear cases are refunded on the spot |
| `report` | This week's savings |
| A voice note | Transcribed if `faster-whisper` is installed, otherwise a polite "please type" |
