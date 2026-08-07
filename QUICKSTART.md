# Quickstart

Five minutes from clone to a running bot.

## 1. Install

```bash
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -r requirements.txt
```

## 2. Make a bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Bot** → **Reset Token** → copy it.
3. **OAuth2 → URL Generator** → scopes `bot` and `applications.commands`, permissions **Send Messages** and **Embed Links**.
4. Open the generated URL and add the bot to your server.

No privileged intents required.

## 3. Configure

```bash
cp .env.example .env
```

Put your token in `DISCORD_TOKEN`. Set `GUILD_ID` to your server's ID —
right-click the server with Developer Mode on and choose **Copy Server ID**.
Without it, slash commands can take an hour to appear.

## 4. Load content

```bash
python admin.py import      # the question bank
python seed.py              # starter resources
```

## 5. Run

```bash
python main.py
```

Type `/ask` in your server.

## Troubleshooting

**Slash commands do not appear.** Set `GUILD_ID` and restart. Check the bot was
invited with the `applications.commands` scope.

**`Configuration error: DISCORD_TOKEN is missing`.** The `.env` file is absent or
the token line is blank.

**`/ask` says there are no questions.** Run `python admin.py import`, then
`python admin.py stats` to confirm the count.

**Someone's aura looks wrong.** `python admin.py recompute-aura` rebuilds the
cached totals from the answer history.
