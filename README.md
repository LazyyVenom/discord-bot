# Champak Chacha

A Discord quiz bot. 1,446 multiple-choice questions across DSA, Python,
JavaScript/TypeScript, backend concepts, OOP/LLD and system design. Answer with
buttons, earn aura, climb the leaderboard.

## Scoring

Three attempts per question, 24 hours apart.

| Attempt | Points |
| --- | --- |
| 1st | 100% |
| 2nd | 50% |
| 3rd | 25% |

A question is worth `difficulty × 10`, so 10 to 50 points. The correct answer
stays hidden while you still have attempts left — it is revealed, with an
explanation, once you get it right or run out.

## Commands

| Command | What it does |
| --- | --- |
| `/ask [category]` | Get a question. Answer with the A/B/C/D buttons. |
| `/profile [user]` | Aura, correct/total, accuracy. |
| `/aura [user]` | Just the aura number. |
| `/leaderboard` | Top 10. |
| `/categories` | Every question and resource category. |
| `/resource [category]` | A random dev resource. |
| `/addresource` | Share one. |
| `/addquestion` | Add a question. Admins only. |
| `/help` | Command reference. |

Admins are members with **Manage Server**, or anyone holding the role named in
`ADMIN_ROLE_ID`.

## Setup

```bash
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then paste your token into .env
```

Create the bot at the [Discord Developer Portal](https://discord.com/developers/applications).
Under **Bot**, copy the token into `.env`. No privileged intents are needed —
the bot uses slash commands and never reads message content.

Invite it with the `bot` and `applications.commands` scopes, and the **Send
Messages** and **Embed Links** permissions.

Load the content and start:

```bash
python admin.py import           # questions from data/questions/
python seed.py                   # starter resources
python main.py
```

Set `GUILD_ID` in `.env` to your server's ID so slash commands appear
immediately; without it a global sync can take up to an hour.

## Admin CLI

```bash
python admin.py stats            # row counts, top users
python admin.py questions        # first 50 questions
python admin.py resources        # every resource
python admin.py import [dir]     # reload the question bank (idempotent)
python admin.py recompute-aura   # rebuild cached counters from answer history
python admin.py reset            # drop everything (asks first)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Layout

```
champak/
  bot.py          client setup, cog loading, error boundary
  config.py       validated settings
  db/             models, async session, question importer
  services/       business rules; scoring.py imports no discord or sqlalchemy
  cogs/           slash commands
  ui/             embeds and the persistent answer buttons
data/questions/   the question bank as JSON
tests/            pytest, service layer
```

The layer that matters is `services/`. It holds every rule and knows nothing
about Discord, so the scoring logic is testable without a gateway connection.

## Adding questions

Drop a JSON file into `data/questions/` and run `python admin.py import`.
Reimporting is idempotent — questions are matched on a hash of their text, so
existing rows are updated rather than duplicated. The same hash also collapses
questions that appear in more than one file, which is why 1,500 source records
load as 1,446 rows.

```json
[
  {
    "question": "What is the time complexity of binary search?",
    "options": [
      {"option_id": 1, "option_value": "O(n)"},
      {"option_id": 2, "option_value": "O(log n)"},
      {"option_id": 3, "option_value": "O(n log n)"},
      {"option_id": 4, "option_value": "O(1)"}
    ],
    "answer_id": 2,
    "answer_explanation": "It halves the search space each iteration.",
    "difficulty_level": 2
  }
]
```

The filename becomes the category, with any `_partN` suffix stripped.

## License

MIT
