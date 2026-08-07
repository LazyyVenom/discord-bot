# Champak Chacha — Phase 1: Rewrite

**Date:** 2026-08-07
**Status:** Approved design, ready for implementation planning
**Scope:** Correctness fixes + slash-command UX + restructure. Excludes new features (Phase 2) and deployment (Phase 3).

## Problem

The bot works, but has defects that make its core mechanic meaningless and its UX dated.

**Point farming.** Nothing prevents re-answering the same question. `bot.py` writes to an
`active_questions` dict that is never read. Before it was discarded, the database showed
`asli_anubhav` holding 59,994 aura from 6 answers.

**Hardcoded backdoor.** `bot.py:122` awards 9,999 points to any user whose username contains
the substring `anubhav`. The companion check against `"YOUR_DISCORD_ID_HERE"` is a placeholder
that never matches.

**Blocking I/O in async handlers.** Every command opens a synchronous SQLAlchemy session on the
event loop thread, stalling the bot for the duration of each query.

**Crashes.** `check_answer` calls `.strip()` on `correct_answer`, which is `None` for any
question lacking both `option_a` and `answer`. `bot.py:151` builds an attribute name from
`correct_option`, raising `AttributeError` on any value outside `A`–`D`.

**Dated UX.** Prefix commands only. Answering a multiple-choice question requires typing
`!answer 3 B` — the user must read an ID off the embed footer and retype it.

**Missing hygiene.** No permission checks on the write commands, no rate limits, no logging
(`Config.logging_level` is read and never used), no tests. `temp.py` is an untracked scratch
file that calls `bot.run()` at import time.

## Decisions

| Question | Decision |
| --- | --- |
| Server scope | Single server. No `guild_id` scoping. |
| Answer rules | 3 attempts per question, 24h apart, points decay 100% → 50% → 25%. |
| Answer reveal | Hidden while attempts remain; revealed on success or exhaustion. |
| Backdoor | Removed. |
| Existing data | Discarded. Database rebuilt from scratch and reseeded. |
| Prefix commands | Dropped. Slash only. |
| Aura storage | Cached columns on `User` (not derived). |
| Who may answer | Only the user who ran `/ask`. |
| Structure | Cogs + pure service layer, async SQLAlchemy. |

## Architecture

```
champak/
  bot.py              # client setup, cog loading, error boundary
  config.py           # validated settings, fails fast
  db/
    models.py         # SQLAlchemy models
    session.py        # async engine + session factory
    import_questions.py  # idempotent JSON question-bank importer
  services/
    scoring.py        # decay, attempts, cooldown        <- pure, no I/O
    questions.py      # selection, eligibility, recording
    resources.py
    users.py          # aura mutation, profile stats
  cogs/
    questions.py      # /ask, answer buttons
    resources.py      # /resource, /addresource
    profile.py        # /profile, /aura, /leaderboard, /categories
    admin.py          # /addquestion (mod-gated)
    meta.py           # /help
  ui/
    embeds.py         # all embed construction
    views.py          # A/B/C/D button view
tests/                # pytest, service layer only
```

The boundary that matters: `services/scoring.py` imports neither `discord` nor SQLAlchemy. It
takes plain data and returns plain data, so every scoring rule is unit-testable without a
database or a gateway connection. Cogs translate Discord objects into service calls and service
results into embeds; they hold no rules of their own.

## Data model

### `Question` (changed)

- **Add** `explanation` (Text, not null) — shown when the answer is revealed. Every imported
  question has one.
- **Add** `import_key` (String, unique, nullable) — SHA-256 of the normalised question text.
  Set on imported questions, null on ones added via `/addquestion`. Makes reimport idempotent.
- **Change** `difficulty` from String to Integer, `1`–`5`, matching the source data. The old
  `easy`/`medium`/`hard` strings are gone.
- **Change** `description` to nullable — the source data has a single question string, so
  `title` carries it and `description` is optional elaboration.
- **Remove** `answer` (Text) — dead column; `correct_option` is authoritative.
- Unchanged: `id`, `category`, `option_a`–`option_d`, `correct_option`, `points`, `is_active`,
  `asked_by`, `created_at`.

`correct_option` is validated to be one of `A`/`B`/`C`/`D` on write, closing the
`AttributeError` path. The four option columns stay nullable in the schema — rewriting them to
`NOT NULL` in SQLite means a table rebuild — but the service layer rejects any question missing
an option, so the "non-MCQ question" path that caused the `None.strip()` crash becomes
unreachable.

`points` is derived from difficulty at import time as `difficulty * 10`, giving 10/20/30/40/50.
This makes harder questions worth more without a separate authoring step.

### `Answer` (changed, ORM class and table name both retained)

- **Add** `attempt_number` (Integer, not null) — `1`, `2`, or `3`.
- **Add** unique constraint on `(question_id, user_id, attempt_number)`.
- **Add** index on `(user_id, question_id)`.
- Unchanged: `id`, `question_id`, `user_id`, `answer_text`, `is_correct`, `points_awarded`,
  `created_at`.

The unique constraint doubles as a race guard — two rapid button clicks cannot both insert
attempt N.

Cooldown state and attempts-remaining are derived by querying these rows. There is no separate
state table and no in-memory dict, so the bot survives a restart mid-question.

### `User` (schema unchanged)

`aura_points`, `correct_answers`, and `total_answers` remain cached columns, starting at `0` on
a fresh database.

Because these are caches, they can drift from the underlying rows. Two mitigations: every write
goes through a single `services/users.py::apply_attempt_result` function, and
`admin.py recompute-aura` recomputes all three from the attempt rows so drift is always one
command away from fixed.

### No `active_questions` state

The question ID is encoded in each button's `custom_id` (`ans:{question_id}:{letter}`), making
the view persistent. Buttons keep working after a restart.

## Scoring service

Two pure functions in `services/scoring.py`:

```python
def award(base_points: int, attempt_number: int) -> int
    # 1 -> base, 2 -> base // 2, 3 -> base // 4, otherwise 0

def check_eligibility(attempts: list[AttemptRecord], now: datetime) -> Eligibility
    # Allowed(attempt_number) | TooSoon(retry_at) | Exhausted | AlreadySolved
```

`AttemptRecord` is a plain dataclass (`attempt_number`, `is_correct`, `created_at`) so the
function never touches an ORM object.

Precedence when several conditions hold: `AlreadySolved` > `Exhausted` > `TooSoon` > `Allowed`.

The cooldown boundary is inclusive: elapsed time `>=` the configured window yields `Allowed`.

Cooldown length and max attempts come from config (`ANSWER_COOLDOWN_HOURS`, default 24;
`MAX_ATTEMPTS`, default 3) so tests run at zero delay and the values are tunable without a code
change.

Integer division is deliberate: a 10-point question yields 10 / 5 / 2.

## Question selection

`services/questions.py::pick_question(session, user_id, category=None)` selects one active
question, preferring never-attempted ones, falling back to retry-eligible ones whose cooldown
has elapsed. Solved and exhausted questions are excluded. Legacy rows do not count as attempts.

Selection happens in SQL (`ORDER BY RANDOM() LIMIT 1`), replacing the current
"load every row into Python, then `random.choice`".

When nothing is eligible, the caller distinguishes two cases so the reply is useful:

- Everything is on cooldown → report the earliest `retry_at`.
- Everything is solved or exhausted → say the pool is finished for this category.

## Commands

All slash commands. All responses route through a shared error boundary.

| Command | Behaviour |
| --- | --- |
| `/ask [category]` | Category autocompletes from distinct DB values. Posts the question embed with four buttons. |
| `/profile [user]` | Aura, correct/total, accuracy, questions remaining. |
| `/aura [user]` | Short aura readout. |
| `/leaderboard` | Top 10 by `aura_points`. |
| `/categories` | Distinct question and resource categories. |
| `/resource [category]` | Random resource, category autocompletes. |
| `/addresource` | Typed parameters: `title`, `url`, `category`, `description` (optional). |
| `/addquestion` | Discord modal (popup form). Mod-gated. |
| `/help` | Command reference. |

### Answer flow

Buttons respond only to the user who ran `/ask`; anyone else clicking gets an ephemeral nudge to
run their own. All answer feedback is ephemeral.

- **Correct** → points awarded per decay tier, explanation shown, buttons disabled.
- **Wrong, attempts remain** → zero points, correct option withheld, next retry time stated,
  buttons disabled on the original message.
- **Wrong, final attempt** → zero points, correct option and explanation revealed.

`total_answers` increments on every recorded attempt; `correct_answers` and `aura_points`
increment only on a correct one. All three move together inside one transaction, replacing the
current split between `record_answer` and the caller in `bot.py`.

### `/addquestion` modal

Discord modals cap at five inputs, so two fields are folded: the four options arrive as one
newline-separated textarea, and title/description share a paragraph field split on the first
blank line. Fields: **Title & description**, **Category**, **Options (one per line, 4 lines)**,
**Correct option (A/B/C/D)**, **Explanation**. Validation errors return to the modal with the
entered values preserved. All pipe-delimited parsing is deleted.

## Permissions, limits, logging

Admin is Discord's `Manage Server` permission, or membership in `ADMIN_ROLE_ID` when that env
var is set. `/addquestion` is admin-only.

Rate limits: `/ask` 1 per 10s per user, `/addresource` 1 per 60s per user, `/leaderboard` 1 per
30s per channel. Exceeding a limit yields an ephemeral "try again in Ns".

`LOGGING_LEVEL` configures the stdlib `logging` root handler to stdout. Command invocations log
at INFO; unexpected exceptions log at ERROR with traceback and return an ephemeral apology
rather than leaking `str(error)` into the channel, as `on_command_error` does today.

Config validates at startup: a missing or empty `DISCORD_TOKEN` exits with a one-line
diagnostic, not a traceback.

## Content: the question bank

The old database has been discarded — no migration is written, and `models.py` defines the
final schema directly. The previous `app.db` is retained out-of-tree as
`app.db.discarded-20260807` and is gitignored.

Content comes from 1,500 MCQs in `data/questions/*.json`, tracked in version control so the
repo can rebuild its own content from a fresh clone. The set was validated against
the schema before this spec was finalised: every question has exactly four options with
`option_id` 1–4, an `answer_id` within that range, non-empty question text, and a non-empty
`answer_explanation`. Zero defects across all 1,500.

Source shape:

```json
{
  "question": "What is the time complexity of binary search on a sorted array?",
  "options": [{"option_id": 1, "option_value": "O(n)"}, ...],
  "answer_id": 2,
  "answer_explanation": "Binary search divides the search space in half ...",
  "difficulty_level": 2
}
```

Field mapping, in `db/import_questions.py`:

| Source | Target |
| --- | --- |
| `question` | `title` |
| `options[n].option_value` ordered by `option_id` | `option_a`–`option_d` |
| `answer_id` (1–4) | `correct_option` (`A`–`D`) |
| `answer_explanation` | `explanation` |
| `difficulty_level` (1–5) | `difficulty`, and `points = difficulty * 10` |
| filename, `_partN` stripped | `category` |

Categories collapse to six: `dsa`, `backend_concepts`, `javascript_typescript`, `oops_lld`,
`python`, `system_design`. Difficulty spread is 133 / 539 / 629 / 179 / 20 across levels 1–5.

The importer validates every record before inserting any, reports all defects at once, and
aborts on the first invalid file rather than half-loading. It is idempotent via `import_key`:
rerunning updates existing rows in place instead of duplicating them. It runs as
`python -m db.import_questions <path>` and via `admin.py import`.

`seed.py` is reduced to resources only; its 6 hand-written questions are superseded.

The importer defaults to `data/questions/`, so `python -m db.import_questions` with no argument
does the right thing. `for_claude/` stays gitignored for scratch material.

## Testing

`pytest` + `pytest-asyncio`. Service layer against in-memory SQLite; no Discord mocking, because
the cogs hold no logic worth testing.

**`scoring.py`** — each decay tier; attempt 4+ yields zero; integer-division rounding; cooldown
boundary at exactly 24h inclusive; `TooSoon` before it, `Allowed` at and after; `Exhausted` at 3
attempts; `AlreadySolved` short-circuits regardless of count; precedence order.

**`questions.py`** — never-attempted preferred; solved excluded; exhausted excluded;
cooling-down excluded; category filter respected; the two empty-pool cases return the right
distinction.

**`users.py`** — counters move together in one transaction; wrong answers bump only
`total_answers`; `recompute-aura` reproduces the cached values from attempt rows.

**`import_questions.py`** — field mapping including `answer_id` → letter; `points` derived from
difficulty; category derived from filename with `_partN` stripped; a malformed record aborts
the whole file with nothing inserted; rerunning is idempotent and does not duplicate; a run
against all ten real files loads exactly 1,500 rows across 6 categories.

## Deletions

- `temp.py` — scratch file, calls `bot.run()` at import.
- The username-substring backdoor.
- All pipe-delimited command parsing.
- `Question.answer` and the non-MCQ code paths branching on it.
- `active_questions`.
- The 6 hand-written questions in `seed.py`, superseded by the imported bank.
- The old `app.db` (moved aside, gitignored).

## Dependencies

Added: `aiosqlite`, `pytest`, `pytest-asyncio`. Dev dependencies split into
`requirements-dev.txt`.

## Out of scope

**Phase 2 (features):** streaks, daily question, duels, resource upvoting, aura-tier roles.
**Phase 3 (deployment):** hosting, process supervision, backups.

Multi-server support is explicitly not built and not designed around; adding it later means a
`guild_id` migration.

## Success criteria

- Answering the same question repeatedly cannot yield more than one award, and no more than
  three attempts total.
- No username or ID grants special scoring.
- A fresh database imports all 1,500 questions across 6 categories; a second import run leaves
  the count unchanged.
- Every `/` command responds without blocking the event loop.
- A bot restart mid-question leaves the buttons working.
- Malformed input to any command yields a readable message, not a traceback.
- `pytest` passes with every rule in the Decisions table covered.
- A fresh clone can rebuild the full question bank with no files from outside the repo.
