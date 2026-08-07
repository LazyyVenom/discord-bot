# Champak Chacha Phase 1 Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Champak Chacha as a slash-command Discord bot with an unexploitable 3-attempt scoring system, backed by a 1,500-question bank.

**Architecture:** A `champak/` package split into four layers. `services/` holds all business rules and imports no Discord code, so every rule is unit-testable without a gateway connection. `cogs/` translates Discord objects into service calls and results into embeds, holding no rules of its own. `db/` owns the async SQLAlchemy engine, models, and the question importer. `ui/` owns embed construction and the persistent answer-button view.

**Tech Stack:** Python 3.13, discord.py 2.6.4 (app commands, `DynamicItem` persistent views, modals), SQLAlchemy 2.0 async with aiosqlite, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-07-champak-chacha-rewrite-design.md`

## Global Constraints

- Single server. No `guild_id` column on any table; no multi-guild scoping anywhere.
- Slash commands only. No `commands.Bot` prefix commands, no `command_prefix` behaviour.
- `services/scoring.py` must not import `discord` or `sqlalchemy`. It takes and returns plain data.
- Max attempts per question: 3. Default cooldown: 24 hours. Both read from config, never hardcoded at a call site.
- Point decay by attempt: 1 → 100%, 2 → 50%, 3 → 25%, 4+ → 0. Integer division.
- Cooldown boundary is inclusive: elapsed `>=` window yields `Allowed`.
- Eligibility precedence: `AlreadySolved` > `Exhausted` > `TooSoon` > `Allowed`.
- The correct option is withheld from the user while attempts remain; revealed only on a correct answer or on exhaustion.
- Only the user who ran `/ask` may use that question's buttons.
- All answer feedback is ephemeral.
- No username or user ID grants special scoring. Ever.
- `points = difficulty * 10`, where difficulty is an integer 1–5.
- Question text is stored in `title`; `description` is nullable and unused by imported questions.
- Never leak `str(exception)` into a Discord channel. Log the traceback, send a generic apology.
- Every DB call is `await`ed against an `AsyncSession`. No synchronous SQLAlchemy on the event loop.

## File Structure

```
main.py                          # entry point (modified)
admin.py                         # CLI (rewritten)
seed.py                          # resources only (rewritten)
pytest.ini                       # new
requirements.txt                 # modified
requirements-dev.txt             # new
champak/
  __init__.py
  config.py                      # validated settings, fails fast
  logging_setup.py               # stdlib logging config
  bot.py                         # client, setup_hook, error boundary
  db/
    __init__.py
    models.py                    # Base, User, Question, Answer, Resource
    session.py                   # async engine + session factory
    import_questions.py          # JSON question-bank importer
  services/
    __init__.py
    scoring.py                   # PURE: decay, attempts, cooldown
    questions.py                 # selection, attempt recording
    users.py                     # aura mutation, leaderboard
    resources.py                 # resource CRUD
  cogs/
    __init__.py
    questions.py                 # /ask + answer flow
    profile.py                   # /profile /aura /leaderboard /categories
    resources.py                 # /resource /addresource
    admin.py                     # /addquestion modal
    meta.py                      # /help
  ui/
    __init__.py
    embeds.py                    # all embed construction
    views.py                     # AnswerButton, AnswerView
tests/
  conftest.py                    # async in-memory session fixture
  test_scoring.py
  test_import_questions.py
  test_questions_service.py
  test_users_service.py
  test_resources_service.py
```

Deleted at the end of Task 1: `temp.py`. Deleted in Task 2: root `models.py`, `db.py`, `config.py`. Deleted in Task 13: root `bot.py`, `utils.py`.

---

### Task 1: Package skeleton, config, logging

**Files:**
- Create: `champak/__init__.py`, `champak/config.py`, `champak/logging_setup.py`
- Create: `requirements-dev.txt`, `pytest.ini`
- Create: `tests/__init__.py`, `tests/test_config.py`
- Modify: `requirements.txt`
- Delete: `temp.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `champak.config.Config` (frozen dataclass with fields `token: str`, `db_url: str`, `logging_level: str`, `guild_id: int | None`, `admin_role_id: int | None`, `answer_cooldown_hours: float`, `max_attempts: int`); `champak.config.ConfigError`; `champak.config.load_config(env: Mapping[str, str] | None = None) -> Config`; `champak.logging_setup.configure_logging(level: str) -> None`.

`load_config` takes an optional mapping so tests never touch the real environment.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
import pytest

from champak.config import Config, ConfigError, load_config

BASE = {"DISCORD_TOKEN": "abc123"}


def test_loads_token():
    cfg = load_config(BASE)
    assert cfg.token == "abc123"


def test_missing_token_raises():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config({})


def test_blank_token_raises():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config({"DISCORD_TOKEN": "   "})


def test_defaults():
    cfg = load_config(BASE)
    assert cfg.db_url == "sqlite+aiosqlite:///app.db"
    assert cfg.logging_level == "INFO"
    assert cfg.guild_id is None
    assert cfg.admin_role_id is None
    assert cfg.answer_cooldown_hours == 24.0
    assert cfg.max_attempts == 3


def test_optional_ints_parsed():
    cfg = load_config({**BASE, "GUILD_ID": "42", "ADMIN_ROLE_ID": "7"})
    assert cfg.guild_id == 42
    assert cfg.admin_role_id == 7


def test_non_numeric_guild_id_raises():
    with pytest.raises(ConfigError, match="GUILD_ID"):
        load_config({**BASE, "GUILD_ID": "not-a-number"})


def test_sync_sqlite_url_is_upgraded_to_async():
    cfg = load_config({**BASE, "DB_URL": "sqlite:///app.db"})
    assert cfg.db_url == "sqlite+aiosqlite:///app.db"


def test_config_is_frozen():
    cfg = load_config(BASE)
    with pytest.raises(Exception):
        cfg.token = "other"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak'`

- [ ] **Step 3: Create the package and config module**

Create empty `champak/__init__.py` and `tests/__init__.py`.

Create `champak/config.py`:

```python
"""Environment-backed settings, validated once at startup."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce a usable Config."""


@dataclass(frozen=True)
class Config:
    token: str
    db_url: str
    logging_level: str
    guild_id: int | None
    admin_role_id: int | None
    answer_cooldown_hours: float
    max_attempts: int


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}") from None


def _positive_number(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{key} must be greater than zero, got {value}")
    return value


def _async_db_url(raw: str) -> str:
    # aiosqlite is required; a plain sqlite:// URL would silently give us a
    # synchronous driver that blocks the event loop.
    if raw.startswith("sqlite:///"):
        return raw.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return raw


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a Config, raising ConfigError with an actionable message."""
    if env is None:
        load_dotenv()
        env = os.environ

    token = env.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "DISCORD_TOKEN is missing or empty. Copy .env.example to .env and "
            "paste your bot token from the Discord Developer Portal."
        )

    max_attempts = int(_positive_number(env, "MAX_ATTEMPTS", 3))

    return Config(
        token=token,
        db_url=_async_db_url(env.get("DB_URL", "").strip() or "sqlite:///app.db"),
        logging_level=env.get("LOGGING_LEVEL", "").strip() or "INFO",
        guild_id=_optional_int(env, "GUILD_ID"),
        admin_role_id=_optional_int(env, "ADMIN_ROLE_ID"),
        answer_cooldown_hours=_positive_number(env, "ANSWER_COOLDOWN_HOURS", 24.0),
        max_attempts=max_attempts,
    )
```

Create `champak/logging_setup.py`:

```python
"""Root logging configuration, driven by LOGGING_LEVEL."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str) -> None:
    resolved = getattr(logging, level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)
    # discord.py's own gateway chatter is noisy at DEBUG and rarely useful.
    logging.getLogger("discord").setLevel(max(resolved, logging.WARNING))
```

- [ ] **Step 4: Add dependencies and pytest config**

Replace `requirements.txt`:

```
SQLAlchemy==2.0.45
discord.py==2.6.4
python-dotenv==1.2.1
aiosqlite==0.21.0
```

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest==8.4.2
pytest-asyncio==1.2.0
```

Create `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
```

Install: `./env/bin/pip install -r requirements-dev.txt`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_config.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Delete the scratch bot**

`temp.py` calls `bot.run()` at import time, so importing anything near it starts a second bot.

```bash
rm temp.py
```

- [ ] **Step 7: Commit**

```bash
git add champak tests requirements.txt requirements-dev.txt pytest.ini
git rm --cached temp.py --ignore-unmatch
git commit -m "feat: add champak package skeleton with validated config"
```

---

### Task 2: Models and async session

**Files:**
- Create: `champak/db/__init__.py`, `champak/db/models.py`, `champak/db/session.py`
- Create: `tests/conftest.py`, `tests/test_models.py`
- Delete: `models.py`, `db.py`, `config.py` (root copies)

**Interfaces:**
- Consumes: `champak.config.Config`.
- Produces: `champak.db.models.Base`, `User`, `Question`, `Answer`, `Resource`; `champak.db.session.create_engine_for(db_url: str) -> AsyncEngine`, `make_session_factory(engine) -> async_sessionmaker[AsyncSession]`, `init_db(engine) -> None`.
- Produces the `session` pytest fixture used by every later test task.

Column reference, used by all later tasks:

`User`: `id`, `discord_id` (unique str), `username`, `aura_points` (int, default 0), `correct_answers` (int, default 0), `total_answers` (int, default 0), `created_at`.

`Question`: `id`, `title` (str, the question text), `description` (Text, nullable), `category` (str), `difficulty` (int 1–5), `option_a`–`option_d` (Text, nullable in schema), `correct_option` (str, one of A/B/C/D), `explanation` (Text, not null), `points` (int), `is_active` (bool, default True), `asked_by` (str, nullable), `import_key` (str, unique, nullable), `created_at`.

`Answer`: `id`, `question_id` (FK), `user_id` (FK), `answer_text`, `is_correct`, `points_awarded`, `attempt_number` (int), `created_at`. Unique on `(question_id, user_id, attempt_number)`; index on `(user_id, question_id)`.

`Resource`: unchanged from the current schema — `id`, `title`, `description`, `url`, `category`, `tags`, `added_by`, `upvotes`, `created_at`.

- [ ] **Step 1: Write the failing tests**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from champak.db.models import Base


@pytest_asyncio.fixture
async def session():
    """An AsyncSession against a fresh in-memory database.

    StaticPool keeps every checkout on the same connection, which is what
    makes ``:memory:`` survive across statements.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
```

Create `tests/test_models.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from champak.db.models import Answer, Question, Resource, User


def make_question(**kw):
    defaults = dict(
        title="What is 2+2?",
        category="dsa",
        difficulty=1,
        option_a="3",
        option_b="4",
        option_c="5",
        option_d="6",
        correct_option="B",
        explanation="Two plus two is four.",
        points=10,
    )
    return Question(**{**defaults, **kw})


async def test_question_roundtrip(session):
    session.add(make_question())
    await session.commit()
    q = (await session.execute(select(Question))).scalar_one()
    assert q.explanation == "Two plus two is four."
    assert q.difficulty == 1
    assert q.is_active is True
    assert q.description is None


async def test_user_defaults_to_zero(session):
    session.add(User(discord_id="1", username="a"))
    await session.commit()
    u = (await session.execute(select(User))).scalar_one()
    assert (u.aura_points, u.correct_answers, u.total_answers) == (0, 0, 0)


async def test_discord_id_is_unique(session):
    session.add_all([User(discord_id="1", username="a"), User(discord_id="1", username="b")])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_import_key_is_unique(session):
    session.add_all([make_question(import_key="k"), make_question(import_key="k")])
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_duplicate_attempt_number_rejected(session):
    q = make_question()
    u = User(discord_id="1", username="a")
    session.add_all([q, u])
    await session.commit()

    session.add(Answer(question_id=q.id, user_id=u.id, answer_text="A",
                       is_correct=False, points_awarded=0, attempt_number=1))
    await session.commit()

    session.add(Answer(question_id=q.id, user_id=u.id, answer_text="B",
                       is_correct=False, points_awarded=0, attempt_number=1))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_sequential_attempt_numbers_allowed(session):
    q = make_question()
    u = User(discord_id="1", username="a")
    session.add_all([q, u])
    await session.commit()

    for n in (1, 2, 3):
        session.add(Answer(question_id=q.id, user_id=u.id, answer_text="A",
                           is_correct=False, points_awarded=0, attempt_number=n))
    await session.commit()
    rows = (await session.execute(select(Answer))).scalars().all()
    assert len(rows) == 3


async def test_resource_roundtrip(session):
    session.add(Resource(title="Docs", url="https://example.com", category="python"))
    await session.commit()
    r = (await session.execute(select(Resource))).scalar_one()
    assert r.upvotes == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.db'`

- [ ] **Step 3: Write the models**

Create empty `champak/db/__init__.py`.

Create `champak/db/models.py`:

```python
"""SQLAlchemy models. This file is the authoritative schema definition."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=False)
    # Cached aggregates. Every write goes through services.users so these
    # stay in step with the answers table; admin.py recompute-aura repairs
    # them if they ever drift.
    aura_points = Column(Integer, nullable=False, default=0)
    correct_answers = Column(Integer, nullable=False, default=0)
    total_answers = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)

    answers = relationship("Answer", back_populates="user")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)  # the question text itself
    description = Column(Text, nullable=True)  # optional elaboration
    category = Column(String, nullable=False)
    difficulty = Column(Integer, nullable=False, default=2)  # 1-5

    # Option columns stay nullable because tightening them in SQLite means a
    # table rebuild; services.questions rejects incomplete questions instead.
    option_a = Column(Text, nullable=True)
    option_b = Column(Text, nullable=True)
    option_c = Column(Text, nullable=True)
    option_d = Column(Text, nullable=True)
    correct_option = Column(String, nullable=False)  # A, B, C or D

    explanation = Column(Text, nullable=False)
    points = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, nullable=False, default=True)
    asked_by = Column(String, nullable=True)
    import_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    answers = relationship("Answer", back_populates="question")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        # Doubles as a race guard: two fast button clicks cannot both insert
        # the same attempt number.
        UniqueConstraint("question_id", "user_id", "attempt_number",
                         name="uq_answer_attempt"),
        Index("ix_answers_user_question", "user_id", "question_id"),
    )

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    answer_text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    points_awarded = Column(Integer, nullable=False, default=0)
    attempt_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    question = relationship("Question", back_populates="answers")
    user = relationship("User", back_populates="answers")


class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String, nullable=False)
    category = Column(String, nullable=False)
    tags = Column(String, nullable=True)
    added_by = Column(String, nullable=True)
    upvotes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)
```

Create `champak/db/session.py`:

```python
"""Async engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from champak.db.models import Base


def create_engine_for(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, echo=False)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False so ORM objects stay readable after commit, which
    # matters when a cog builds an embed from a just-written row.
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_models.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Delete the superseded root modules**

These are replaced by `champak/db/models.py`, `champak/db/session.py`, and `champak/config.py`. Root `bot.py` and `utils.py` still import them and will break; they are rewritten in Task 13. Tests do not touch them.

```bash
git rm models.py db.py config.py
```

- [ ] **Step 6: Commit**

```bash
git add champak/db tests/conftest.py tests/test_models.py
git commit -m "feat: add async SQLAlchemy models and session factory"
```

---

### Task 3: Scoring service (pure)

**Files:**
- Create: `champak/services/__init__.py`, `champak/services/scoring.py`
- Create: `tests/test_scoring.py`

**Interfaces:**
- Consumes: nothing. This module must not import `discord` or `sqlalchemy`.
- Produces: `AttemptRecord(attempt_number: int, is_correct: bool, created_at: datetime)`; `Allowed(attempt_number: int)`, `TooSoon(retry_at: datetime)`, `Exhausted()`, `AlreadySolved()`; `Eligibility` union; `award(base_points: int, attempt_number: int) -> int`; `check_eligibility(attempts: Sequence[AttemptRecord], now: datetime, *, max_attempts: int = 3, cooldown: timedelta = timedelta(hours=24)) -> Eligibility`.

This is the heart of the fix. Test it hardest.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scoring.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from champak.services.scoring import (
    Allowed,
    AlreadySolved,
    AttemptRecord,
    Exhausted,
    TooSoon,
    award,
    check_eligibility,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(hours=24)


def attempt(n, correct=False, ago=timedelta(days=30)):
    return AttemptRecord(attempt_number=n, is_correct=correct, created_at=NOW - ago)


# ---- award ----

@pytest.mark.parametrize("n,expected", [(1, 40), (2, 20), (3, 10), (4, 0), (99, 0)])
def test_award_decay_tiers(n, expected):
    assert award(40, n) == expected


def test_award_uses_integer_division():
    # A 10-point question pays 10 / 5 / 2 -- never a fraction.
    assert [award(10, n) for n in (1, 2, 3)] == [10, 5, 2]


def test_award_rejects_attempt_below_one():
    assert award(40, 0) == 0


def test_award_never_negative():
    assert award(1, 3) == 0


# ---- check_eligibility ----

def test_no_attempts_allows_first():
    assert check_eligibility([], NOW) == Allowed(attempt_number=1)


def test_after_one_stale_wrong_attempt_allows_second():
    assert check_eligibility([attempt(1)], NOW) == Allowed(attempt_number=2)


def test_solved_short_circuits():
    assert check_eligibility([attempt(1, correct=True)], NOW) == AlreadySolved()


def test_solved_wins_over_exhausted():
    attempts = [attempt(1), attempt(2), attempt(3, correct=True)]
    assert check_eligibility(attempts, NOW) == AlreadySolved()


def test_solved_wins_over_cooldown():
    attempts = [attempt(1, correct=True, ago=timedelta(minutes=1))]
    assert check_eligibility(attempts, NOW) == AlreadySolved()


def test_exhausted_at_max_attempts():
    attempts = [attempt(1), attempt(2), attempt(3)]
    assert check_eligibility(attempts, NOW) == Exhausted()


def test_exhausted_wins_over_cooldown():
    attempts = [attempt(1), attempt(2), attempt(3, ago=timedelta(minutes=1))]
    assert check_eligibility(attempts, NOW) == Exhausted()


def test_too_soon_reports_retry_time():
    last = NOW - timedelta(hours=1)
    result = check_eligibility(
        [AttemptRecord(1, False, last)], NOW
    )
    assert result == TooSoon(retry_at=last + DAY)


def test_cooldown_boundary_is_inclusive():
    # Exactly 24h elapsed must be allowed, not blocked.
    last = NOW - DAY
    assert check_eligibility([AttemptRecord(1, False, last)], NOW) == Allowed(2)


def test_one_second_before_boundary_is_too_soon():
    last = NOW - DAY + timedelta(seconds=1)
    assert isinstance(check_eligibility([AttemptRecord(1, False, last)], NOW), TooSoon)


def test_cooldown_measured_from_latest_attempt():
    attempts = [attempt(1, ago=timedelta(days=10)),
                attempt(2, ago=timedelta(hours=2))]
    result = check_eligibility(attempts, NOW)
    assert result == TooSoon(retry_at=NOW - timedelta(hours=2) + DAY)


def test_attempts_out_of_order_still_handled():
    attempts = [attempt(2, ago=timedelta(hours=2)), attempt(1, ago=timedelta(days=10))]
    result = check_eligibility(attempts, NOW)
    assert result == TooSoon(retry_at=NOW - timedelta(hours=2) + DAY)


def test_custom_max_attempts_respected():
    assert check_eligibility([attempt(1)], NOW, max_attempts=1) == Exhausted()


def test_zero_cooldown_allows_immediate_retry():
    attempts = [attempt(1, ago=timedelta(seconds=0))]
    result = check_eligibility(attempts, NOW, cooldown=timedelta(0))
    assert result == Allowed(attempt_number=2)


def test_naive_datetimes_are_treated_as_utc():
    naive_now = datetime(2026, 8, 7, 12, 0)
    attempts = [AttemptRecord(1, False, datetime(2026, 8, 6, 12, 0))]
    assert check_eligibility(attempts, naive_now) == Allowed(2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.services'`

- [ ] **Step 3: Write the scoring service**

Create empty `champak/services/__init__.py`.

Create `champak/services/scoring.py`:

```python
"""Scoring rules. Pure functions over plain data.

This module deliberately imports neither discord nor sqlalchemy: every rule
here is testable without a gateway connection or a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_COOLDOWN = timedelta(hours=24)

# Fraction of base points kept, indexed by attempt number.
_DECAY_DIVISOR = {1: 1, 2: 2, 3: 4}


@dataclass(frozen=True)
class AttemptRecord:
    attempt_number: int
    is_correct: bool
    created_at: datetime


@dataclass(frozen=True)
class Allowed:
    attempt_number: int


@dataclass(frozen=True)
class TooSoon:
    retry_at: datetime


@dataclass(frozen=True)
class Exhausted:
    pass


@dataclass(frozen=True)
class AlreadySolved:
    pass


Eligibility = Allowed | TooSoon | Exhausted | AlreadySolved


def award(base_points: int, attempt_number: int) -> int:
    """Points earned for a correct answer on the given attempt.

    Attempt 1 pays in full, 2 pays half, 3 pays a quarter, and anything
    beyond pays nothing. Integer division throughout, so a 10-point question
    pays 10 / 5 / 2.
    """
    divisor = _DECAY_DIVISOR.get(attempt_number)
    if divisor is None:
        return 0
    return max(0, base_points // divisor)


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC so SQLite round-trips compare cleanly."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def check_eligibility(
    attempts: Sequence[AttemptRecord],
    now: datetime,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cooldown: timedelta = DEFAULT_COOLDOWN,
) -> Eligibility:
    """Decide whether this user may attempt this question right now.

    Precedence is AlreadySolved > Exhausted > TooSoon > Allowed.
    """
    if any(a.is_correct for a in attempts):
        return AlreadySolved()

    if len(attempts) >= max_attempts:
        return Exhausted()

    if attempts:
        latest = max(_as_utc(a.created_at) for a in attempts)
        retry_at = latest + cooldown
        if _as_utc(now) < retry_at:
            return TooSoon(retry_at=retry_at)

    return Allowed(attempt_number=len(attempts) + 1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_scoring.py -v`
Expected: PASS, 24 tests

- [ ] **Step 5: Verify the purity constraint**

Run: `./env/bin/python -c "
import ast, sys
tree = ast.parse(open('champak/services/scoring.py').read())
mods = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        mods |= {a.name.split('.')[0] for a in node.names}
    elif isinstance(node, ast.ImportFrom) and node.module:
        mods.add(node.module.split('.')[0])
banned = mods & {'discord', 'sqlalchemy', 'champak'}
print('imports:', sorted(mods))
sys.exit(1) if banned else print('PURE: no discord/sqlalchemy/champak imports')
"`

Expected: `PURE: no discord/sqlalchemy/champak imports`

- [ ] **Step 6: Commit**

```bash
git add champak/services tests/test_scoring.py
git commit -m "feat: add pure scoring service with attempt decay and cooldown"
```

---

### Task 4: Question bank importer

**Files:**
- Create: `champak/db/import_questions.py`
- Create: `tests/test_import_questions.py`

**Interfaces:**
- Consumes: `champak.db.models.Question`, the `session` fixture.
- Produces: `category_for_filename(name: str) -> str`; `letter_for(answer_id: int) -> str`; `import_key_for(question_text: str) -> str`; `ImportError_ = QuestionImportError`; `parse_file(path: Path) -> list[dict]`; `import_all(session, directory: Path) -> ImportStats`; `ImportStats(created: int, updated: int, files: int)`.

Source records look like:

```json
{
  "question": "What is the time complexity of binary search on a sorted array?",
  "options": [{"option_id": 1, "option_value": "O(n)"}, ...],
  "answer_id": 2,
  "answer_explanation": "Binary search divides the search space in half ...",
  "difficulty_level": 2
}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_import_questions.py`:

```python
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from champak.db.import_questions import (
    QuestionImportError,
    category_for_filename,
    import_all,
    import_key_for,
    letter_for,
    parse_file,
)
from champak.db.models import Question

REAL_DATA = Path("data/questions")


def record(**kw):
    base = {
        "question": "What is 2+2?",
        "options": [
            {"option_id": 1, "option_value": "3"},
            {"option_id": 2, "option_value": "4"},
            {"option_id": 3, "option_value": "5"},
            {"option_id": 4, "option_value": "6"},
        ],
        "answer_id": 2,
        "answer_explanation": "Two plus two is four.",
        "difficulty_level": 1,
    }
    return {**base, **kw}


def write(tmp_path, name, records):
    p = tmp_path / name
    p.write_text(json.dumps(records))
    return p


# ---- pure helpers ----

@pytest.mark.parametrize("name,expected", [
    ("dsa_part1.json", "dsa"),
    ("dsa_part2.json", "dsa"),
    ("python.json", "python"),
    ("backend_concepts_part1.json", "backend_concepts"),
    ("javascript_typescript.json", "javascript_typescript"),
    ("system_design_part2.json", "system_design"),
])
def test_category_for_filename(name, expected):
    assert category_for_filename(name) == expected


@pytest.mark.parametrize("aid,letter", [(1, "A"), (2, "B"), (3, "C"), (4, "D")])
def test_letter_for(aid, letter):
    assert letter_for(aid) == letter


def test_import_key_is_stable_and_whitespace_insensitive():
    assert import_key_for("What is 2+2?") == import_key_for("  What is 2+2?  ")


def test_import_key_differs_by_text():
    assert import_key_for("a") != import_key_for("b")


# ---- parse_file validation ----

def test_parse_file_accepts_valid(tmp_path):
    assert len(parse_file(write(tmp_path, "dsa_part1.json", [record()]))) == 1


def test_parse_file_rejects_missing_explanation(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(answer_explanation="")])
    with pytest.raises(QuestionImportError, match="explanation"):
        parse_file(p)


def test_parse_file_rejects_wrong_option_count(tmp_path):
    p = write(tmp_path, "dsa_part1.json",
              [record(options=[{"option_id": 1, "option_value": "x"}])])
    with pytest.raises(QuestionImportError, match="4 options"):
        parse_file(p)


def test_parse_file_rejects_answer_id_out_of_range(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(answer_id=9)])
    with pytest.raises(QuestionImportError, match="answer_id"):
        parse_file(p)


def test_parse_file_rejects_bad_difficulty(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(difficulty_level=0)])
    with pytest.raises(QuestionImportError, match="difficulty"):
        parse_file(p)


def test_parse_file_rejects_blank_question(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(question="  ")])
    with pytest.raises(QuestionImportError, match="question text"):
        parse_file(p)


def test_error_names_the_file_and_index(tmp_path):
    p = write(tmp_path, "dsa_part1.json", [record(), record(answer_id=9)])
    with pytest.raises(QuestionImportError, match=r"dsa_part1\.json.*index 1"):
        parse_file(p)


# ---- import_all ----

async def test_import_maps_all_fields(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    await import_all(session, tmp_path)

    q = (await session.execute(select(Question))).scalar_one()
    assert q.title == "What is 2+2?"
    assert (q.option_a, q.option_b, q.option_c, q.option_d) == ("3", "4", "5", "6")
    assert q.correct_option == "B"
    assert q.explanation == "Two plus two is four."
    assert q.category == "dsa"
    assert q.difficulty == 1
    assert q.points == 10
    assert q.description is None
    assert q.import_key == import_key_for("What is 2+2?")


async def test_points_derived_from_difficulty(session, tmp_path):
    write(tmp_path, "dsa_part1.json",
          [record(question=f"Q{d}", difficulty_level=d) for d in (1, 3, 5)])
    await import_all(session, tmp_path)

    rows = (await session.execute(select(Question).order_by(Question.difficulty))).scalars().all()
    assert [(r.difficulty, r.points) for r in rows] == [(1, 10), (3, 30), (5, 50)]


async def test_parts_merge_into_one_category(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(question="Q1")])
    write(tmp_path, "dsa_part2.json", [record(question="Q2")])
    await import_all(session, tmp_path)

    cats = (await session.execute(select(Question.category).distinct())).scalars().all()
    assert cats == ["dsa"]


async def test_rerun_is_idempotent(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    first = await import_all(session, tmp_path)
    second = await import_all(session, tmp_path)

    assert (first.created, first.updated) == (1, 0)
    assert (second.created, second.updated) == (0, 1)
    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1


async def test_rerun_updates_changed_explanation(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record()])
    await import_all(session, tmp_path)
    write(tmp_path, "dsa_part1.json", [record(answer_explanation="Revised.")])
    await import_all(session, tmp_path)

    q = (await session.execute(select(Question))).scalar_one()
    assert q.explanation == "Revised."


async def test_invalid_file_inserts_nothing(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(), record(question="Q2", answer_id=9)])
    with pytest.raises(QuestionImportError):
        await import_all(session, tmp_path)

    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 0


async def test_duplicate_text_within_run_is_collapsed(session, tmp_path):
    write(tmp_path, "dsa_part1.json", [record(), record()])
    await import_all(session, tmp_path)
    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1


async def test_missing_directory_raises(session, tmp_path):
    with pytest.raises(QuestionImportError, match="no JSON files"):
        await import_all(session, tmp_path / "nope")


# ---- the real bank ----

@pytest.mark.skipif(not REAL_DATA.exists(), reason="question bank not present")
async def test_real_bank_imports_cleanly(session):
    stats = await import_all(session, REAL_DATA)
    assert stats.files == 10
    assert stats.created == 1500

    count = (await session.execute(select(func.count()).select_from(Question))).scalar_one()
    assert count == 1500

    cats = sorted((await session.execute(select(Question.category).distinct())).scalars().all())
    assert cats == [
        "backend_concepts", "dsa", "javascript_typescript",
        "oops_lld", "python", "system_design",
    ]

    bad = (await session.execute(
        select(func.count()).select_from(Question).where(
            Question.explanation.is_(None) | (Question.explanation == "")
        )
    )).scalar_one()
    assert bad == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_import_questions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.db.import_questions'`

- [ ] **Step 3: Write the importer**

Create `champak/db/import_questions.py`:

```python
"""Load the JSON question bank into the database.

Validation happens for a whole file before anything is written, so a single
malformed record aborts that file rather than half-loading it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from champak.db.models import Question

log = logging.getLogger(__name__)

DEFAULT_DIRECTORY = Path("data/questions")
LETTERS = ("A", "B", "C", "D")
_PART_SUFFIX = re.compile(r"_part\d+$")


class QuestionImportError(RuntimeError):
    """Raised when the source data cannot be trusted."""


@dataclass(frozen=True)
class ImportStats:
    files: int
    created: int
    updated: int


def category_for_filename(name: str) -> str:
    """`dsa_part1.json` -> `dsa`. Parts of a set share one category."""
    return _PART_SUFFIX.sub("", Path(name).stem)


def letter_for(answer_id: int) -> str:
    return LETTERS[answer_id - 1]


def import_key_for(question_text: str) -> str:
    """Stable identity for a question, so reruns update instead of duplicate."""
    normalised = " ".join(question_text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _validate(record: object, source: str, index: int) -> dict:
    where = f"{source} index {index}"

    if not isinstance(record, dict):
        raise QuestionImportError(f"{where}: expected an object, got {type(record).__name__}")

    text = str(record.get("question", "")).strip()
    if not text:
        raise QuestionImportError(f"{where}: missing question text")

    options = record.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise QuestionImportError(f"{where}: expected exactly 4 options")

    ids = sorted(o.get("option_id") for o in options)
    if ids != [1, 2, 3, 4]:
        raise QuestionImportError(f"{where}: option_ids must be 1-4, got {ids}")

    values = {o["option_id"]: str(o.get("option_value", "")).strip() for o in options}
    for oid, value in values.items():
        if not value:
            raise QuestionImportError(f"{where}: option {oid} is empty")

    answer_id = record.get("answer_id")
    if answer_id not in (1, 2, 3, 4):
        raise QuestionImportError(f"{where}: answer_id must be 1-4, got {answer_id!r}")

    explanation = str(record.get("answer_explanation", "")).strip()
    if not explanation:
        raise QuestionImportError(f"{where}: missing explanation")

    difficulty = record.get("difficulty_level")
    if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
        raise QuestionImportError(f"{where}: difficulty must be 1-5, got {difficulty!r}")

    return {
        "title": text,
        "option_a": values[1],
        "option_b": values[2],
        "option_c": values[3],
        "option_d": values[4],
        "correct_option": letter_for(answer_id),
        "explanation": explanation,
        "difficulty": difficulty,
        "points": difficulty * 10,
        "category": category_for_filename(source),
        "import_key": import_key_for(text),
    }


def parse_file(path: Path) -> list[dict]:
    """Read and fully validate one file. Raises before returning anything."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise QuestionImportError(f"{path.name}: invalid JSON - {exc}") from exc

    if not isinstance(raw, list):
        raise QuestionImportError(f"{path.name}: expected a top-level JSON array")

    return [_validate(record, path.name, i) for i, record in enumerate(raw)]


async def import_all(session, directory: Path = DEFAULT_DIRECTORY) -> ImportStats:
    """Validate every file, then upsert every question by import_key."""
    directory = Path(directory)
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise QuestionImportError(f"{directory}: no JSON files found")

    # Validate everything up front so a bad file in the middle cannot leave a
    # partially-populated database behind.
    parsed: dict[str, dict] = {}
    for path in paths:
        for row in parse_file(path):
            parsed[row["import_key"]] = row

    existing = {
        q.import_key: q
        for q in (
            await session.execute(
                select(Question).where(Question.import_key.in_(parsed.keys()))
            )
        ).scalars()
    }

    created = updated = 0
    for key, row in parsed.items():
        question = existing.get(key)
        if question is None:
            session.add(Question(**row))
            created += 1
        else:
            for field, value in row.items():
                setattr(question, field, value)
            updated += 1

    await session.commit()
    log.info(
        "imported %d files: %d created, %d updated", len(paths), created, updated
    )
    return ImportStats(files=len(paths), created=created, updated=updated)


async def _main() -> None:
    import sys

    from champak.config import load_config
    from champak.db.session import create_engine_for, init_db, make_session_factory
    from champak.logging_setup import configure_logging

    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIRECTORY
    config = load_config()
    configure_logging(config.logging_level)

    engine = create_engine_for(config.db_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    async with factory() as session:
        stats = await import_all(session, directory)
    await engine.dispose()

    print(
        f"{stats.files} files -> {stats.created} created, {stats.updated} updated"
    )


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_import_questions.py -v`
Expected: PASS, 22 tests including the 1,500-row real-data test

- [ ] **Step 5: Populate the real database**

Run: `./env/bin/python -m champak.db.import_questions`
Expected: `10 files -> 1500 created, 0 updated`

Run it a second time to confirm idempotence.
Expected: `10 files -> 0 created, 1500 updated`

- [ ] **Step 6: Commit**

```bash
git add champak/db/import_questions.py tests/test_import_questions.py
git commit -m "feat: add idempotent question-bank importer"
```

---

### Task 5: Question service

**Files:**
- Create: `champak/services/questions.py`
- Create: `tests/test_questions_service.py`

**Interfaces:**
- Consumes: `champak.services.scoring` (all names), `champak.db.models.Question`/`Answer`/`User`.
- Produces:
  - `QuestionPick(question: Question | None, reason: str, retry_at: datetime | None)` where `reason` is one of `"ok"`, `"empty"`, `"all_cooling_down"`, `"all_done"`.
  - `async pick_question(session, user_id: int, category: str | None, now: datetime, *, max_attempts: int, cooldown: timedelta) -> QuestionPick`
  - `async load_attempts(session, user_id: int, question_id: int) -> list[AttemptRecord]`
  - `async get_question(session, question_id: int) -> Question | None`
  - `async list_categories(session) -> list[str]`
  - `AnswerOutcome(is_correct: bool, points_awarded: int, attempt_number: int, attempts_remaining: int, reveal: bool, correct_option: str, explanation: str, retry_at: datetime | None)`
  - `Rejected(eligibility: Eligibility)`
  - `async submit_answer(session, *, user: User, question: Question, chosen: str, now: datetime, max_attempts: int, cooldown: timedelta) -> AnswerOutcome | Rejected`

`submit_answer` writes the attempt row and updates the user's cached counters inside one transaction.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_questions_service.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from champak.db.models import Answer, Question, User
from champak.services.questions import (
    AnswerOutcome,
    Rejected,
    get_question,
    list_categories,
    load_attempts,
    pick_question,
    submit_answer,
)
from champak.services.scoring import AlreadySolved, Exhausted, TooSoon

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(hours=24)
LIMITS = {"max_attempts": 3, "cooldown": DAY}


async def make_user(session, discord_id="1"):
    user = User(discord_id=discord_id, username="tester")
    session.add(user)
    await session.commit()
    return user


async def make_question(session, title="Q", category="dsa", points=40):
    q = Question(
        title=title, category=category, difficulty=4,
        option_a="w", option_b="x", option_c="y", option_d="z",
        correct_option="B", explanation="Because x.", points=points,
    )
    session.add(q)
    await session.commit()
    return q


async def add_attempt(session, user, question, n, correct=False, ago=timedelta(days=30)):
    session.add(Answer(
        question_id=question.id, user_id=user.id, answer_text="A",
        is_correct=correct, points_awarded=0, attempt_number=n,
        created_at=NOW - ago,
    ))
    await session.commit()


# ---- pick_question ----

async def test_empty_pool(session):
    user = await make_user(session)
    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question is None and pick.reason == "empty"


async def test_picks_unattempted(session):
    user = await make_user(session)
    q = await make_question(session)
    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question.id == q.id and pick.reason == "ok"


async def test_skips_solved(session):
    user = await make_user(session)
    solved = await make_question(session, title="solved")
    fresh = await make_question(session, title="fresh")
    await add_attempt(session, user, solved, 1, correct=True)

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question.id == fresh.id


async def test_skips_exhausted(session):
    user = await make_user(session)
    q = await make_question(session)
    for n in (1, 2, 3):
        await add_attempt(session, user, q, n)

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question is None and pick.reason == "all_done"


async def test_skips_cooling_down_and_reports_retry_at(session):
    user = await make_user(session)
    q = await make_question(session)
    await add_attempt(session, user, q, 1, ago=timedelta(hours=1))

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question is None
    assert pick.reason == "all_cooling_down"
    assert pick.retry_at == NOW - timedelta(hours=1) + DAY


async def test_reports_earliest_retry_across_questions(session):
    user = await make_user(session)
    q1 = await make_question(session, title="q1")
    q2 = await make_question(session, title="q2")
    await add_attempt(session, user, q1, 1, ago=timedelta(hours=1))
    await add_attempt(session, user, q2, 1, ago=timedelta(hours=5))

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.retry_at == NOW - timedelta(hours=5) + DAY


async def test_retryable_question_is_offered(session):
    user = await make_user(session)
    q = await make_question(session)
    await add_attempt(session, user, q, 1, ago=timedelta(days=2))

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question.id == q.id


async def test_prefers_unattempted_over_retryable(session):
    user = await make_user(session)
    old = await make_question(session, title="old")
    await add_attempt(session, user, old, 1, ago=timedelta(days=2))
    fresh = await make_question(session, title="fresh")

    for _ in range(10):
        pick = await pick_question(session, user.id, None, NOW, **LIMITS)
        assert pick.question.id == fresh.id


async def test_category_filter(session):
    user = await make_user(session)
    await make_question(session, title="d", category="dsa")
    py = await make_question(session, title="p", category="python")

    pick = await pick_question(session, user.id, "python", NOW, **LIMITS)
    assert pick.question.id == py.id


async def test_unknown_category_is_empty(session):
    user = await make_user(session)
    await make_question(session, category="dsa")
    pick = await pick_question(session, user.id, "nope", NOW, **LIMITS)
    assert pick.question is None and pick.reason == "empty"


async def test_inactive_questions_excluded(session):
    user = await make_user(session)
    q = await make_question(session)
    q.is_active = False
    await session.commit()

    pick = await pick_question(session, user.id, None, NOW, **LIMITS)
    assert pick.question is None and pick.reason == "empty"


async def test_other_users_attempts_do_not_block(session):
    mine = await make_user(session, "1")
    theirs = await make_user(session, "2")
    q = await make_question(session)
    await add_attempt(session, theirs, q, 1, correct=True)

    pick = await pick_question(session, mine.id, None, NOW, **LIMITS)
    assert pick.question.id == q.id


# ---- load_attempts / helpers ----

async def test_load_attempts_returns_records(session):
    user = await make_user(session)
    q = await make_question(session)
    await add_attempt(session, user, q, 1)

    records = await load_attempts(session, user.id, q.id)
    assert [r.attempt_number for r in records] == [1]


async def test_list_categories_sorted_and_distinct(session):
    await make_question(session, title="a", category="python")
    await make_question(session, title="b", category="dsa")
    await make_question(session, title="c", category="dsa")
    assert await list_categories(session) == ["dsa", "python"]


async def test_get_question_missing_returns_none(session):
    assert await get_question(session, 999) is None


# ---- submit_answer ----

async def test_correct_first_attempt_pays_full(session):
    user = await make_user(session)
    q = await make_question(session, points=40)

    out = await submit_answer(session, user=user, question=q, chosen="B",
                              now=NOW, **LIMITS)
    assert isinstance(out, AnswerOutcome)
    assert out.is_correct and out.points_awarded == 40
    assert out.attempt_number == 1 and out.reveal is True
    assert out.explanation == "Because x."
    assert user.aura_points == 40
    assert user.correct_answers == 1
    assert user.total_answers == 1


async def test_wrong_answer_withholds_correct_option(session):
    user = await make_user(session)
    q = await make_question(session)

    out = await submit_answer(session, user=user, question=q, chosen="A",
                              now=NOW, **LIMITS)
    assert out.is_correct is False
    assert out.points_awarded == 0
    assert out.reveal is False
    assert out.attempts_remaining == 2
    assert out.retry_at == NOW + DAY
    assert user.aura_points == 0
    assert user.correct_answers == 0
    assert user.total_answers == 1


async def test_third_wrong_attempt_reveals(session):
    user = await make_user(session)
    q = await make_question(session)
    await add_attempt(session, user, q, 1)
    await add_attempt(session, user, q, 2)

    out = await submit_answer(session, user=user, question=q, chosen="A",
                              now=NOW, **LIMITS)
    assert out.reveal is True
    assert out.correct_option == "B"
    assert out.attempts_remaining == 0


async def test_second_attempt_correct_pays_half(session):
    user = await make_user(session)
    q = await make_question(session, points=40)
    await add_attempt(session, user, q, 1)

    out = await submit_answer(session, user=user, question=q, chosen="B",
                              now=NOW, **LIMITS)
    assert out.points_awarded == 20 and user.aura_points == 20


async def test_third_attempt_correct_pays_quarter(session):
    user = await make_user(session)
    q = await make_question(session, points=40)
    await add_attempt(session, user, q, 1)
    await add_attempt(session, user, q, 2)

    out = await submit_answer(session, user=user, question=q, chosen="B",
                              now=NOW, **LIMITS)
    assert out.points_awarded == 10 and user.aura_points == 10


async def test_answer_is_case_insensitive(session):
    user = await make_user(session)
    q = await make_question(session)
    out = await submit_answer(session, user=user, question=q, chosen="b",
                              now=NOW, **LIMITS)
    assert out.is_correct is True


async def test_resubmitting_solved_is_rejected(session):
    user = await make_user(session)
    q = await make_question(session, points=40)
    await submit_answer(session, user=user, question=q, chosen="B", now=NOW, **LIMITS)

    out = await submit_answer(session, user=user, question=q, chosen="B",
                              now=NOW + timedelta(days=5), **LIMITS)
    assert isinstance(out, Rejected)
    assert out.eligibility == AlreadySolved()
    assert user.aura_points == 40  # not doubled


async def test_farming_is_impossible(session):
    """The original exploit: hammer the same question for unlimited points."""
    user = await make_user(session)
    q = await make_question(session, points=40)

    for i in range(20):
        await submit_answer(session, user=user, question=q, chosen="B",
                            now=NOW + timedelta(days=i), **LIMITS)

    assert user.aura_points == 40
    assert user.total_answers == 1


async def test_wrong_answers_capped_at_three(session):
    user = await make_user(session)
    q = await make_question(session)

    for i in range(10):
        await submit_answer(session, user=user, question=q, chosen="A",
                            now=NOW + timedelta(days=i), **LIMITS)

    assert user.total_answers == 3
    out = await submit_answer(session, user=user, question=q, chosen="A",
                              now=NOW + timedelta(days=99), **LIMITS)
    assert isinstance(out, Rejected) and out.eligibility == Exhausted()


async def test_answering_during_cooldown_is_rejected(session):
    user = await make_user(session)
    q = await make_question(session)
    await submit_answer(session, user=user, question=q, chosen="A", now=NOW, **LIMITS)

    out = await submit_answer(session, user=user, question=q, chosen="C",
                              now=NOW + timedelta(hours=1), **LIMITS)
    assert isinstance(out, Rejected)
    assert isinstance(out.eligibility, TooSoon)
    assert user.total_answers == 1


async def test_invalid_option_letter_rejected(session):
    user = await make_user(session)
    q = await make_question(session)
    with pytest.raises(ValueError, match="option"):
        await submit_answer(session, user=user, question=q, chosen="Z",
                            now=NOW, **LIMITS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_questions_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.services.questions'`

- [ ] **Step 3: Write the question service**

Create `champak/services/questions.py`:

```python
"""Question selection and answer recording."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from champak.db.models import Answer, Question, User
from champak.services.scoring import (
    Allowed,
    AttemptRecord,
    Eligibility,
    award,
    check_eligibility,
)

log = logging.getLogger(__name__)

VALID_OPTIONS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class QuestionPick:
    question: Question | None
    reason: str  # "ok" | "empty" | "all_cooling_down" | "all_done"
    retry_at: datetime | None = None


@dataclass(frozen=True)
class AnswerOutcome:
    is_correct: bool
    points_awarded: int
    attempt_number: int
    attempts_remaining: int
    reveal: bool
    correct_option: str
    explanation: str
    retry_at: datetime | None


@dataclass(frozen=True)
class Rejected:
    eligibility: Eligibility


async def get_question(session, question_id: int) -> Question | None:
    return await session.get(Question, question_id)


async def list_categories(session) -> list[str]:
    rows = await session.execute(
        select(Question.category).where(Question.is_active.is_(True)).distinct()
    )
    return sorted(rows.scalars().all())


async def load_attempts(session, user_id: int, question_id: int) -> list[AttemptRecord]:
    rows = await session.execute(
        select(Answer)
        .where(Answer.user_id == user_id, Answer.question_id == question_id)
        .order_by(Answer.attempt_number)
    )
    return [
        AttemptRecord(
            attempt_number=a.attempt_number,
            is_correct=a.is_correct,
            created_at=a.created_at,
        )
        for a in rows.scalars()
    ]


async def pick_question(
    session,
    user_id: int,
    category: str | None,
    now: datetime,
    *,
    max_attempts: int,
    cooldown: timedelta,
) -> QuestionPick:
    """Choose a question this user may attempt right now.

    Never-attempted questions are preferred; retry-eligible ones are the
    fallback. Selection happens in SQL so we never load the whole bank.
    """
    base = select(Question).where(Question.is_active.is_(True))
    if category:
        base = base.where(Question.category == category)

    attempted_ids = (
        select(Answer.question_id).where(Answer.user_id == user_id).distinct()
    )

    unattempted = await session.execute(
        base.where(~Question.id.in_(attempted_ids)).order_by(func.random()).limit(1)
    )
    question = unattempted.scalars().first()
    if question is not None:
        return QuestionPick(question=question, reason="ok")

    # Nothing fresh left. Fall back to questions with attempts remaining,
    # checking eligibility per question.
    candidates = (await session.execute(base.where(Question.id.in_(attempted_ids)))).scalars().all()
    if not candidates:
        # No attempted questions either, so the filtered pool is genuinely empty.
        any_at_all = (await session.execute(base.limit(1))).scalars().first()
        return QuestionPick(question=None, reason="empty" if any_at_all is None else "all_done")

    soonest: datetime | None = None
    for candidate in candidates:
        attempts = await load_attempts(session, user_id, candidate.id)
        verdict = check_eligibility(
            attempts, now, max_attempts=max_attempts, cooldown=cooldown
        )
        if isinstance(verdict, Allowed):
            return QuestionPick(question=candidate, reason="ok")
        retry_at = getattr(verdict, "retry_at", None)
        if retry_at is not None and (soonest is None or retry_at < soonest):
            soonest = retry_at

    if soonest is not None:
        return QuestionPick(question=None, reason="all_cooling_down", retry_at=soonest)
    return QuestionPick(question=None, reason="all_done")


async def submit_answer(
    session,
    *,
    user: User,
    question: Question,
    chosen: str,
    now: datetime,
    max_attempts: int,
    cooldown: timedelta,
) -> AnswerOutcome | Rejected:
    """Record an attempt and update the user's cached counters atomically."""
    letter = chosen.strip().upper()
    if letter not in VALID_OPTIONS:
        raise ValueError(f"chosen must be one of {VALID_OPTIONS}, got {chosen!r}")

    attempts = await load_attempts(session, user.id, question.id)
    verdict = check_eligibility(
        attempts, now, max_attempts=max_attempts, cooldown=cooldown
    )
    if not isinstance(verdict, Allowed):
        return Rejected(eligibility=verdict)

    attempt_number = verdict.attempt_number
    is_correct = letter == question.correct_option.strip().upper()
    points = award(question.points, attempt_number) if is_correct else 0
    remaining = max(0, max_attempts - attempt_number)

    session.add(
        Answer(
            question_id=question.id,
            user_id=user.id,
            answer_text=letter,
            is_correct=is_correct,
            points_awarded=points,
            attempt_number=attempt_number,
            created_at=now,
        )
    )

    user.total_answers += 1
    if is_correct:
        user.correct_answers += 1
        user.aura_points += points

    await session.commit()

    reveal = is_correct or remaining == 0
    log.info(
        "user=%s question=%s attempt=%d correct=%s points=%d",
        user.discord_id, question.id, attempt_number, is_correct, points,
    )
    return AnswerOutcome(
        is_correct=is_correct,
        points_awarded=points,
        attempt_number=attempt_number,
        attempts_remaining=remaining,
        reveal=reveal,
        correct_option=question.correct_option.strip().upper(),
        explanation=question.explanation,
        retry_at=None if reveal else now + cooldown,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_questions_service.py -v`
Expected: PASS, 27 tests

- [ ] **Step 5: Commit**

```bash
git add champak/services/questions.py tests/test_questions_service.py
git commit -m "feat: add question selection and attempt recording service"
```

---

### Task 6: User service

**Files:**
- Create: `champak/services/users.py`
- Create: `tests/test_users_service.py`

**Interfaces:**
- Consumes: `champak.db.models.User`/`Answer`.
- Produces: `async get_or_create_user(session, discord_id: str, username: str) -> User`; `async top_users(session, limit: int = 10) -> list[User]`; `async recompute_all(session) -> list[tuple[str, int, int]]` returning `(discord_id, old_aura, new_aura)` for changed users; `accuracy(user: User) -> float`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_users_service.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select

from champak.db.models import Answer, Question, User
from champak.services.users import accuracy, get_or_create_user, recompute_all, top_users

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


async def test_creates_user_once(session):
    a = await get_or_create_user(session, "1", "anu")
    b = await get_or_create_user(session, "1", "anu")
    assert a.id == b.id
    assert len((await session.execute(select(User))).scalars().all()) == 1


async def test_username_refreshed_on_lookup(session):
    await get_or_create_user(session, "1", "old_name")
    user = await get_or_create_user(session, "1", "new_name")
    assert user.username == "new_name"


async def test_new_user_starts_at_zero(session):
    user = await get_or_create_user(session, "1", "anu")
    assert (user.aura_points, user.correct_answers, user.total_answers) == (0, 0, 0)


async def test_no_username_gets_special_treatment(session):
    """The old backdoor awarded 9999 to anyone matching 'anubhav'."""
    for name in ("anubhav", "asli_anubhav", "ANUBHAV", "anubhav_choubey"):
        user = await get_or_create_user(session, name, name)
        assert user.aura_points == 0


async def test_top_users_ordered_by_aura(session):
    for did, aura in (("1", 10), ("2", 50), ("3", 30)):
        user = await get_or_create_user(session, did, did)
        user.aura_points = aura
    await session.commit()

    assert [u.discord_id for u in await top_users(session)] == ["2", "3", "1"]


async def test_top_users_respects_limit(session):
    for did in "12345":
        await get_or_create_user(session, did, did)
    assert len(await top_users(session, limit=2)) == 2


async def test_accuracy_handles_zero_answers(session):
    user = await get_or_create_user(session, "1", "anu")
    assert accuracy(user) == 0.0


async def test_accuracy_percentage(session):
    user = await get_or_create_user(session, "1", "anu")
    user.correct_answers, user.total_answers = 3, 4
    assert accuracy(user) == 75.0


async def test_recompute_repairs_drift(session):
    user = await get_or_create_user(session, "1", "anu")
    q = Question(title="Q", category="dsa", difficulty=1, option_a="a",
                 option_b="b", option_c="c", option_d="d", correct_option="B",
                 explanation="e", points=10)
    session.add(q)
    await session.commit()

    session.add(Answer(question_id=q.id, user_id=user.id, answer_text="B",
                       is_correct=True, points_awarded=10, attempt_number=1,
                       created_at=NOW))
    user.aura_points = 99999  # simulated drift
    user.correct_answers = 42
    user.total_answers = 7
    await session.commit()

    changed = await recompute_all(session)
    assert changed == [("1", 99999, 10)]
    assert user.aura_points == 10
    assert user.correct_answers == 1
    assert user.total_answers == 1


async def test_recompute_is_a_noop_when_consistent(session):
    user = await get_or_create_user(session, "1", "anu")
    assert await recompute_all(session) == []
    assert user.aura_points == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_users_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.services.users'`

- [ ] **Step 3: Write the user service**

Create `champak/services/users.py`:

```python
"""User lookup, leaderboard, and cached-counter repair."""

from __future__ import annotations

import logging

from sqlalchemy import case, func, select

from champak.db.models import Answer, User

log = logging.getLogger(__name__)


async def get_or_create_user(session, discord_id: str, username: str) -> User:
    """Fetch the user, creating them on first sight.

    No identity gets special scoring. If you are looking for the old
    'infinite aura' branch, it was deleted on purpose.
    """
    existing = (
        await session.execute(select(User).where(User.discord_id == str(discord_id)))
    ).scalars().first()

    if existing is not None:
        if existing.username != username:
            existing.username = username
            await session.commit()
        return existing

    user = User(discord_id=str(discord_id), username=username)
    session.add(user)
    await session.commit()
    return user


async def top_users(session, limit: int = 10) -> list[User]:
    rows = await session.execute(
        select(User).order_by(User.aura_points.desc(), User.id).limit(limit)
    )
    return list(rows.scalars())


def accuracy(user: User) -> float:
    if not user.total_answers:
        return 0.0
    return user.correct_answers / user.total_answers * 100


async def recompute_all(session) -> list[tuple[str, int, int]]:
    """Rebuild cached counters from the answers table.

    Returns (discord_id, old_aura, new_aura) for every user that changed.
    """
    totals = {
        row.user_id: row
        for row in (
            await session.execute(
                select(
                    Answer.user_id.label("user_id"),
                    func.coalesce(func.sum(Answer.points_awarded), 0).label("aura"),
                    func.count().label("total"),
                    func.coalesce(
                        func.sum(case((Answer.is_correct.is_(True), 1), else_=0)), 0
                    ).label("correct"),
                ).group_by(Answer.user_id)
            )
        ).all()
    }

    changed: list[tuple[str, int, int]] = []
    for user in (await session.execute(select(User))).scalars():
        row = totals.get(user.id)
        aura = int(row.aura) if row else 0
        total = int(row.total) if row else 0
        correct = int(row.correct) if row else 0

        if (user.aura_points, user.correct_answers, user.total_answers) != (
            aura, correct, total
        ):
            changed.append((user.discord_id, user.aura_points, aura))
            user.aura_points, user.correct_answers, user.total_answers = (
                aura, correct, total
            )

    if changed:
        await session.commit()
        log.warning("recomputed cached counters for %d users", len(changed))
    return changed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_users_service.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add champak/services/users.py tests/test_users_service.py
git commit -m "feat: add user service with leaderboard and counter repair"
```

---

### Task 7: Resource service

**Files:**
- Create: `champak/services/resources.py`
- Create: `tests/test_resources_service.py`

**Interfaces:**
- Consumes: `champak.db.models.Resource`.
- Produces: `async random_resource(session, category: str | None) -> Resource | None`; `async add_resource(session, *, title: str, url: str, category: str, description: str | None, added_by: str) -> Resource`; `async list_resource_categories(session) -> list[str]`; `InvalidResource` exception.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resources_service.py`:

```python
import pytest
from sqlalchemy import select

from champak.db.models import Resource
from champak.services.resources import (
    InvalidResource,
    add_resource,
    list_resource_categories,
    random_resource,
)


async def test_add_and_fetch(session):
    await add_resource(session, title="Docs", url="https://example.com",
                       category="python", description=None, added_by="anu")
    r = (await session.execute(select(Resource))).scalar_one()
    assert r.title == "Docs" and r.added_by == "anu" and r.upvotes == 0


async def test_rejects_non_http_url(session):
    with pytest.raises(InvalidResource, match="http"):
        await add_resource(session, title="X", url="javascript:alert(1)",
                           category="python", description=None, added_by="anu")


async def test_rejects_blank_title(session):
    with pytest.raises(InvalidResource, match="title"):
        await add_resource(session, title="   ", url="https://example.com",
                           category="python", description=None, added_by="anu")


async def test_rejects_blank_category(session):
    with pytest.raises(InvalidResource, match="category"):
        await add_resource(session, title="X", url="https://example.com",
                           category=" ", description=None, added_by="anu")


async def test_category_is_normalised(session):
    r = await add_resource(session, title="X", url="https://example.com",
                           category="  Python  ", description=None, added_by="anu")
    assert r.category == "python"


async def test_random_resource_none_when_empty(session):
    assert await random_resource(session, None) is None


async def test_random_resource_respects_category(session):
    await add_resource(session, title="A", url="https://a.com", category="dsa",
                       description=None, added_by="anu")
    py = await add_resource(session, title="B", url="https://b.com", category="python",
                            description=None, added_by="anu")
    got = await random_resource(session, "python")
    assert got.id == py.id


async def test_unknown_category_returns_none(session):
    await add_resource(session, title="A", url="https://a.com", category="dsa",
                       description=None, added_by="anu")
    assert await random_resource(session, "nope") is None


async def test_list_categories_sorted(session):
    for cat in ("python", "dsa", "dsa"):
        await add_resource(session, title=cat, url="https://x.com", category=cat,
                           description=None, added_by="anu")
    assert await list_resource_categories(session) == ["dsa", "python"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./env/bin/python -m pytest tests/test_resources_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'champak.services.resources'`

- [ ] **Step 3: Write the resource service**

Create `champak/services/resources.py`:

```python
"""Resource storage and retrieval."""

from __future__ import annotations

from sqlalchemy import func, select

from champak.db.models import Resource

ALLOWED_SCHEMES = ("http://", "https://")


class InvalidResource(ValueError):
    """Raised when a submitted resource fails validation."""


async def add_resource(
    session,
    *,
    title: str,
    url: str,
    category: str,
    description: str | None,
    added_by: str,
) -> Resource:
    clean_title = title.strip()
    if not clean_title:
        raise InvalidResource("A resource needs a title.")

    clean_url = url.strip()
    if not clean_url.lower().startswith(ALLOWED_SCHEMES):
        raise InvalidResource("The url must start with http:// or https://")

    clean_category = category.strip().lower()
    if not clean_category:
        raise InvalidResource("A resource needs a category.")

    resource = Resource(
        title=clean_title,
        url=clean_url,
        category=clean_category,
        description=(description or "").strip() or None,
        added_by=added_by,
    )
    session.add(resource)
    await session.commit()
    return resource


async def random_resource(session, category: str | None) -> Resource | None:
    query = select(Resource)
    if category:
        query = query.where(Resource.category == category.strip().lower())
    rows = await session.execute(query.order_by(func.random()).limit(1))
    return rows.scalars().first()


async def list_resource_categories(session) -> list[str]:
    rows = await session.execute(select(Resource.category).distinct())
    return sorted(rows.scalars().all())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./env/bin/python -m pytest tests/test_resources_service.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add champak/services/resources.py tests/test_resources_service.py
git commit -m "feat: add resource service with url validation"
```

---

### Task 8: Embeds and the persistent answer view

**Files:**
- Create: `champak/ui/__init__.py`, `champak/ui/embeds.py`, `champak/ui/views.py`

**Interfaces:**
- Consumes: `champak.services.questions.AnswerOutcome`, `champak.services.users.accuracy`, models.
- Produces:
  - `embeds.question_embed(question, asker_name: str) -> discord.Embed`
  - `embeds.outcome_embed(outcome: AnswerOutcome, question) -> discord.Embed`
  - `embeds.rejection_embed(eligibility) -> discord.Embed`
  - `embeds.no_question_embed(pick: QuestionPick, category: str | None) -> discord.Embed`
  - `embeds.profile_embed(user, avatar_url: str | None) -> discord.Embed`
  - `embeds.leaderboard_embed(users: list[User]) -> discord.Embed`
  - `embeds.resource_embed(resource) -> discord.Embed`
  - `embeds.categories_embed(question_cats, resource_cats) -> discord.Embed`
  - `embeds.help_embed() -> discord.Embed`
  - `views.AnswerButton` (a `discord.ui.DynamicItem`), `views.AnswerView(question_id: int, asker_id: int)`, `views.CUSTOM_ID_TEMPLATE`

There are no unit tests in this task: these functions only assemble Discord objects. Task 9 exercises them end-to-end.

- [ ] **Step 1: Write the embeds module**

Create empty `champak/ui/__init__.py`.

Create `champak/ui/embeds.py`:

```python
"""Every Discord embed the bot sends is built here."""

from __future__ import annotations

import discord

from champak.services.questions import AnswerOutcome, QuestionPick
from champak.services.scoring import AlreadySolved, Exhausted, TooSoon
from champak.services.users import accuracy

OPTION_LETTERS = ("A", "B", "C", "D")
DIFFICULTY_LABELS = {1: "Very easy", 2: "Easy", 3: "Medium", 4: "Hard", 5: "Brutal"}


def _timestamp(when) -> str:
    """Discord renders this as a live-updating relative time."""
    return f"<t:{int(when.timestamp())}:R>"


def question_embed(question, asker_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=question.title,
        description=question.description or None,
        color=discord.Color.blurple(),
    )
    options = "\n".join(
        f"**{letter})** {getattr(question, f'option_{letter.lower()}')}"
        for letter in OPTION_LETTERS
    )
    embed.add_field(name="Options", value=options, inline=False)
    embed.add_field(name="Category", value=question.category, inline=True)
    embed.add_field(
        name="Difficulty",
        value=DIFFICULTY_LABELS.get(question.difficulty, str(question.difficulty)),
        inline=True,
    )
    embed.add_field(name="Worth", value=f"🔥 {question.points}", inline=True)
    embed.set_footer(text=f"Asked by {asker_name} · only they can answer")
    return embed


def outcome_embed(outcome: AnswerOutcome, question) -> discord.Embed:
    if outcome.is_correct:
        embed = discord.Embed(
            title="✅ Correct",
            description=f"Attempt {outcome.attempt_number} — **+{outcome.points_awarded}** aura.",
            color=discord.Color.green(),
        )
    elif outcome.attempts_remaining:
        plural = "attempt" if outcome.attempts_remaining == 1 else "attempts"
        embed = discord.Embed(
            title="❌ Not quite",
            description=(
                f"{outcome.attempts_remaining} {plural} left. "
                f"Try again {_timestamp(outcome.retry_at)}."
            ),
            color=discord.Color.orange(),
        )
        # Deliberately no correct option here: revealing it would make the
        # retry free.
        return embed
    else:
        embed = discord.Embed(
            title="❌ Out of attempts",
            description="No aura this time.",
            color=discord.Color.red(),
        )

    correct_text = getattr(question, f"option_{outcome.correct_option.lower()}")
    embed.add_field(
        name="Answer",
        value=f"**{outcome.correct_option})** {correct_text}",
        inline=False,
    )
    embed.add_field(name="Why", value=outcome.explanation, inline=False)
    return embed


def rejection_embed(eligibility) -> discord.Embed:
    if isinstance(eligibility, AlreadySolved):
        text = "You have already answered this one correctly."
    elif isinstance(eligibility, Exhausted):
        text = "You have used all three attempts on this question."
    elif isinstance(eligibility, TooSoon):
        text = f"Too soon — you can try this again {_timestamp(eligibility.retry_at)}."
    else:
        text = "You cannot answer this question right now."
    return discord.Embed(title="⏳ Hold on", description=text,
                         color=discord.Color.greyple())


def no_question_embed(pick: QuestionPick, category: str | None) -> discord.Embed:
    scope = f" in **{category}**" if category else ""
    if pick.reason == "all_cooling_down" and pick.retry_at is not None:
        text = f"Everything{scope} is on cooldown. Next one unlocks {_timestamp(pick.retry_at)}."
    elif pick.reason == "all_done":
        text = f"You have finished everything{scope}. Try another category."
    else:
        text = f"No questions found{scope}."
    return discord.Embed(title="🎯 Nothing to ask", description=text,
                         color=discord.Color.greyple())


def profile_embed(user, avatar_url: str | None) -> discord.Embed:
    embed = discord.Embed(title=f"{user.username}", color=discord.Color.gold())
    embed.add_field(name="🔥 Aura", value=str(user.aura_points), inline=True)
    embed.add_field(
        name="✅ Correct",
        value=f"{user.correct_answers}/{user.total_answers}",
        inline=True,
    )
    embed.add_field(name="🎯 Accuracy", value=f"{accuracy(user):.1f}%", inline=True)
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    return embed


def leaderboard_embed(users) -> discord.Embed:
    embed = discord.Embed(title="🏆 Aura Leaderboard", color=discord.Color.purple())
    if not users:
        embed.description = "Nobody has scored yet. Be first with `/ask`."
        return embed

    medals = ("🥇", "🥈", "🥉")
    lines = [
        f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{u.username}** — "
        f"🔥 {u.aura_points} ({u.correct_answers} correct)"
        for i, u in enumerate(users)
    ]
    embed.description = "\n".join(lines)
    return embed


def resource_embed(resource) -> discord.Embed:
    embed = discord.Embed(
        title=resource.title,
        description=resource.description or None,
        url=resource.url,
        color=discord.Color.green(),
    )
    embed.add_field(name="Category", value=resource.category, inline=True)
    if resource.added_by:
        embed.add_field(name="Added by", value=resource.added_by, inline=True)
    return embed


def categories_embed(question_cats, resource_cats) -> discord.Embed:
    embed = discord.Embed(title="📋 Categories", color=discord.Color.blurple())
    embed.add_field(
        name="Questions",
        value=", ".join(question_cats) or "none yet",
        inline=False,
    )
    embed.add_field(
        name="Resources",
        value=", ".join(resource_cats) or "none yet",
        inline=False,
    )
    return embed


def help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Champak Chacha",
        description="Answer questions, earn aura, climb the board.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Questions",
        value=(
            "`/ask [category]` — get a question and answer it with the buttons\n"
            "Three attempts per question, 24h apart. "
            "Full points first try, half on the second, a quarter on the third."
        ),
        inline=False,
    )
    embed.add_field(
        name="Resources",
        value="`/resource [category]` — a random dev resource\n"
              "`/addresource` — share one",
        inline=False,
    )
    embed.add_field(
        name="Stats",
        value="`/profile [user]` · `/aura [user]` · `/leaderboard` · `/categories`",
        inline=False,
    )
    return embed
```

- [ ] **Step 2: Write the persistent view**

Create `champak/ui/views.py`:

```python
"""The A/B/C/D answer buttons.

These are DynamicItems rather than a plain View so the question id can live
in the custom_id. That makes them survive a bot restart: discord.py rebuilds
the handler from the custom_id instead of needing the original View object
to still be in memory.
"""

from __future__ import annotations

import re

import discord

CUSTOM_ID_TEMPLATE = r"cc:ans:(?P<qid>\d+):(?P<letter>[A-D]):(?P<uid>\d+)"
LETTERS = ("A", "B", "C", "D")


class AnswerButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=CUSTOM_ID_TEMPLATE,
):
    def __init__(self, question_id: int, letter: str, asker_id: int):
        self.question_id = question_id
        self.letter = letter
        self.asker_id = asker_id
        super().__init__(
            discord.ui.Button(
                label=letter,
                style=discord.ButtonStyle.secondary,
                custom_id=f"cc:ans:{question_id}:{letter}:{asker_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["qid"]), match["letter"], int(match["uid"]))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.asker_id:
            return True
        await interaction.response.send_message(
            "That is not your question — run `/ask` to get your own.",
            ephemeral=True,
        )
        return False

    async def callback(self, interaction: discord.Interaction):
        # The cog owns the answer flow; this keeps rules out of the UI layer.
        await interaction.client.handle_answer(
            interaction, self.question_id, self.letter
        )


class AnswerView(discord.ui.View):
    def __init__(self, question_id: int, asker_id: int):
        super().__init__(timeout=None)
        for letter in LETTERS:
            self.add_item(AnswerButton(question_id, letter, asker_id))
```

- [ ] **Step 3: Verify both modules import cleanly**

Run: `./env/bin/python -c "
from champak.ui import embeds, views
e = embeds.help_embed()
print('help embed fields:', len(e.fields))
v = views.AnswerView(7, 123)
print('buttons:', [i.item.label for i in v.children])
print('custom_ids:', [i.item.custom_id for i in v.children])
import re
assert re.fullmatch(views.CUSTOM_ID_TEMPLATE, 'cc:ans:7:B:123')
print('template matches')
"`

Expected: 3 fields, buttons `['A','B','C','D']`, custom_ids like `cc:ans:7:A:123`, and `template matches`

- [ ] **Step 4: Commit**

```bash
git add champak/ui
git commit -m "feat: add embeds and persistent answer-button view"
```

---

### Task 9: Bot core, error boundary, entry point

**Files:**
- Create: `champak/bot.py`
- Create: `champak/cogs/__init__.py`
- Modify: `main.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: config, session factory, `champak.ui.views.AnswerButton`.
- Produces: `ChampakBot` with attributes `config: Config`, `session_factory`, `engine`, and methods `session()` (async context manager), `handle_answer(interaction, question_id, letter)` (assigned by the questions cog in Task 10), `is_admin(interaction) -> bool`.
- Produces: `champak.bot.run() -> None`.

`AnswerButton.callback` calls `interaction.client.handle_answer`, so `ChampakBot` defines a placeholder that the questions cog overrides on load. This keeps the UI layer free of business logic.

- [ ] **Step 1: Write the bot core**

Create empty `champak/cogs/__init__.py`.

Create `champak/bot.py`:

```python
"""Discord client setup, cog loading, and the global error boundary."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from champak.config import Config, ConfigError, load_config
from champak.db.session import create_engine_for, init_db, make_session_factory
from champak.logging_setup import configure_logging
from champak.ui.views import AnswerButton

log = logging.getLogger(__name__)

COGS = (
    "champak.cogs.questions",
    "champak.cogs.profile",
    "champak.cogs.resources",
    "champak.cogs.admin",
    "champak.cogs.meta",
)


class ChampakBot(commands.Bot):
    def __init__(self, config: Config):
        # No prefix commands exist any more, but commands.Bot still wants a
        # prefix; this one is unreachable because message_content is off.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
        )
        self.config = config
        self.engine = create_engine_for(config.db_url)
        self.session_factory = make_session_factory(self.engine)

    def session(self):
        return self.session_factory()

    async def setup_hook(self) -> None:
        await init_db(self.engine)
        self.add_dynamic_items(AnswerButton)

        for module in COGS:
            await self.load_extension(module)
            log.info("loaded %s", module)

        if self.config.guild_id:
            # Guild-scoped sync is instant; global sync can take an hour.
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d commands to guild %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.warning(
                "synced %d commands globally; set GUILD_ID for instant updates",
                len(synced),
            )

        self.tree.on_error = self.on_app_command_error

    async def close(self) -> None:
        await super().close()
        await self.engine.dispose()

    async def on_ready(self) -> None:
        log.info("online as %s (id %s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game(name="/ask"))

    def is_admin(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is not None and perms.manage_guild:
            return True
        role_id = self.config.admin_role_id
        if role_id is None:
            return False
        roles = getattr(interaction.user, "roles", ())
        return any(role.id == role_id for role in roles)

    async def handle_answer(self, interaction, question_id: int, letter: str) -> None:
        """Replaced by the questions cog on load."""
        await interaction.response.send_message(
            "The question system is still starting up. Try again in a moment.",
            ephemeral=True,
        )

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Slow down — try again in {error.retry_after:.0f}s."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to do that."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You cannot use that command here."
        else:
            # Never surface str(error): it can carry internals.
            log.exception("unhandled error in /%s",
                          interaction.command.name if interaction.command else "?",
                          exc_info=error)
            message = "Something broke on my end. It has been logged."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.exception("could not deliver the error message")


async def _run_async(config: Config) -> None:
    bot = ChampakBot(config)
    async with bot:
        await bot.start(config.token)


def run() -> None:
    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from None

    configure_logging(config.logging_level)
    try:
        asyncio.run(_run_async(config))
    except KeyboardInterrupt:
        log.info("stopped by user")
```

- [ ] **Step 2: Rewrite the entry point**

Replace `main.py`:

```python
from champak.bot import run

if __name__ == "__main__":
    run()
```

- [ ] **Step 3: Update the env template**

Replace `.env.example`:

```
# Discord bot token, from the Developer Portal
DISCORD_TOKEN=your_discord_bot_token_here

# Your server's ID. Slash commands sync instantly when this is set;
# leaving it blank falls back to a global sync that can take an hour.
GUILD_ID=

# Optional. Members with this role count as admins in addition to
# anyone holding the Manage Server permission.
ADMIN_ROLE_ID=

# Database. sqlite:// is rewritten to sqlite+aiosqlite:// automatically.
DB_URL=sqlite:///app.db

# DEBUG, INFO, WARNING, ERROR
LOGGING_LEVEL=INFO

# Scoring rules
ANSWER_COOLDOWN_HOURS=24
MAX_ATTEMPTS=3
```

- [ ] **Step 4: Verify the bot constructs without connecting**

The cogs do not exist yet, so `setup_hook` is not exercised here — only construction and config wiring.

Run: `./env/bin/python -c "
from champak.bot import ChampakBot
from champak.config import Config

cfg = Config(token='x', db_url='sqlite+aiosqlite:///:memory:', logging_level='INFO',
             guild_id=None, admin_role_id=99, answer_cooldown_hours=24.0, max_attempts=3)
bot = ChampakBot(cfg)
print('prefix commands:', len(bot.commands))
print('config wired:', bot.config.max_attempts, bot.config.admin_role_id)
print('session factory:', bot.session_factory is not None)
"`

Expected: `prefix commands: 0`, `config wired: 3 99`, `session factory: True`

Run: `./env/bin/python -c "import main; print('entry point imports')"`
Expected: `entry point imports`

- [ ] **Step 5: Commit**

```bash
git add champak/bot.py champak/cogs/__init__.py main.py .env.example
git commit -m "feat: add bot core with error boundary and guild-scoped sync"
```

---

### Task 10: Questions cog — `/ask` and the answer flow

**Files:**
- Create: `champak/cogs/questions.py`

**Interfaces:**
- Consumes: `services.questions` (all), `services.users.get_or_create_user`, `ui.embeds`, `ui.views.AnswerView`.
- Produces: the `/ask` command and `bot.handle_answer`.

- [ ] **Step 1: Write the cog**

Create `champak/cogs/questions.py`:

```python
"""The /ask command and the button-driven answer flow."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from champak.services import questions as qsvc
from champak.services.users import get_or_create_user
from champak.ui import embeds
from champak.ui.views import AnswerView

log = logging.getLogger(__name__)


class Questions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # The buttons call through the client; point that at this cog.
        bot.handle_answer = self.handle_answer

    def _limits(self) -> dict:
        return {
            "max_attempts": self.bot.config.max_attempts,
            "cooldown": timedelta(hours=self.bot.config.answer_cooldown_hours),
        }

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        async with self.bot.session() as session:
            names = await qsvc.list_categories(session)
        matches = [n for n in names if current.lower() in n.lower()][:25]
        return [app_commands.Choice(name=n, value=n) for n in matches]

    @app_commands.command(name="ask", description="Get a question to answer")
    @app_commands.describe(category="Narrow it to one topic")
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.checks.cooldown(1, 10.0)
    async def ask(self, interaction: discord.Interaction, category: str | None = None):
        now = datetime.now(timezone.utc)
        async with self.bot.session() as session:
            user = await get_or_create_user(
                session, str(interaction.user.id), interaction.user.name
            )
            pick = await qsvc.pick_question(
                session, user.id, category, now, **self._limits()
            )

            if pick.question is None:
                await interaction.response.send_message(
                    embed=embeds.no_question_embed(pick, category), ephemeral=True
                )
                return

            await interaction.response.send_message(
                embed=embeds.question_embed(pick.question, interaction.user.display_name),
                view=AnswerView(pick.question.id, interaction.user.id),
            )

    async def handle_answer(
        self, interaction: discord.Interaction, question_id: int, letter: str
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self.bot.session() as session:
            question = await qsvc.get_question(session, question_id)
            if question is None:
                await interaction.response.send_message(
                    "That question no longer exists.", ephemeral=True
                )
                return

            user = await get_or_create_user(
                session, str(interaction.user.id), interaction.user.name
            )
            result = await qsvc.submit_answer(
                session, user=user, question=question, chosen=letter,
                now=now, **self._limits(),
            )

            if isinstance(result, qsvc.Rejected):
                await interaction.response.send_message(
                    embed=embeds.rejection_embed(result.eligibility), ephemeral=True
                )
                return

            await interaction.response.send_message(
                embed=embeds.outcome_embed(result, question), ephemeral=True
            )

        # Retire the buttons so the message cannot be clicked again.
        try:
            await interaction.message.edit(view=None)
        except (discord.HTTPException, AttributeError):
            log.debug("could not clear buttons on message", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Questions(bot))
```

- [ ] **Step 2: Verify the cog loads and wires the handler**

Run: `./env/bin/python -c "
import asyncio
from champak.bot import ChampakBot
from champak.config import Config

cfg = Config(token='x', db_url='sqlite+aiosqlite:///:memory:', logging_level='WARNING',
             guild_id=None, admin_role_id=None, answer_cooldown_hours=24.0, max_attempts=3)

async def main():
    bot = ChampakBot(cfg)
    await bot.load_extension('champak.cogs.questions')
    names = [c.name for c in bot.tree.get_commands()]
    print('commands:', names)
    print('handler rebound:', bot.handle_answer.__qualname__)
    await bot.engine.dispose()

asyncio.run(main())
"`

Expected: `commands: ['ask']` and `handler rebound: Questions.handle_answer`

- [ ] **Step 3: Commit**

```bash
git add champak/cogs/questions.py
git commit -m "feat: add /ask command and button answer flow"
```

---

### Task 11: Profile cog

**Files:**
- Create: `champak/cogs/profile.py`

**Interfaces:**
- Consumes: `services.users`, `services.questions.list_categories`, `services.resources.list_resource_categories`, `ui.embeds`.
- Produces: `/profile`, `/aura`, `/leaderboard`, `/categories`.

- [ ] **Step 1: Write the cog**

Create `champak/cogs/profile.py`:

```python
"""Stats commands: profile, aura, leaderboard, categories."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.services.questions import list_categories
from champak.services.resources import list_resource_categories
from champak.services.users import get_or_create_user, top_users
from champak.ui import embeds


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="See someone's stats")
    @app_commands.describe(member="Whose profile to show (defaults to you)")
    async def profile(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        async with self.bot.session() as session:
            user = await get_or_create_user(session, str(target.id), target.name)
            embed = embeds.profile_embed(user, target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="aura", description="Check aura points")
    @app_commands.describe(member="Whose aura to check (defaults to you)")
    async def aura(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        async with self.bot.session() as session:
            user = await get_or_create_user(session, str(target.id), target.name)
            points = user.aura_points
        await interaction.response.send_message(
            f"🔥 {target.mention} has **{points}** aura."
        )

    @app_commands.command(name="leaderboard", description="Top 10 by aura")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.channel_id)
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.bot.session() as session:
            users = await top_users(session, limit=10)
        await interaction.response.send_message(embed=embeds.leaderboard_embed(users))

    @app_commands.command(name="categories", description="List every category")
    async def categories(self, interaction: discord.Interaction):
        async with self.bot.session() as session:
            question_cats = await list_categories(session)
            resource_cats = await list_resource_categories(session)
        await interaction.response.send_message(
            embed=embeds.categories_embed(question_cats, resource_cats)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
```

- [ ] **Step 2: Verify the cog loads**

Run: `./env/bin/python -c "
import asyncio
from champak.bot import ChampakBot
from champak.config import Config

cfg = Config(token='x', db_url='sqlite+aiosqlite:///:memory:', logging_level='WARNING',
             guild_id=None, admin_role_id=None, answer_cooldown_hours=24.0, max_attempts=3)

async def main():
    bot = ChampakBot(cfg)
    await bot.load_extension('champak.cogs.profile')
    print('commands:', sorted(c.name for c in bot.tree.get_commands()))
    await bot.engine.dispose()

asyncio.run(main())
"`

Expected: `commands: ['aura', 'categories', 'leaderboard', 'profile']`

- [ ] **Step 3: Commit**

```bash
git add champak/cogs/profile.py
git commit -m "feat: add profile, aura, leaderboard and categories commands"
```

---

### Task 12: Resources cog

**Files:**
- Create: `champak/cogs/resources.py`

**Interfaces:**
- Consumes: `services.resources`, `ui.embeds`.
- Produces: `/resource`, `/addresource`.

- [ ] **Step 1: Write the cog**

Create `champak/cogs/resources.py`:

```python
"""Resource sharing commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.services.resources import (
    InvalidResource,
    add_resource,
    list_resource_categories,
    random_resource,
)
from champak.ui import embeds


class Resources(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def category_autocomplete(self, interaction: discord.Interaction, current: str):
        async with self.bot.session() as session:
            names = await list_resource_categories(session)
        matches = [n for n in names if current.lower() in n.lower()][:25]
        return [app_commands.Choice(name=n, value=n) for n in matches]

    @app_commands.command(name="resource", description="Get a random dev resource")
    @app_commands.describe(category="Narrow it to one topic")
    @app_commands.autocomplete(category=category_autocomplete)
    async def resource(
        self, interaction: discord.Interaction, category: str | None = None
    ):
        async with self.bot.session() as session:
            found = await random_resource(session, category)

        if found is None:
            scope = f" in **{category}**" if category else ""
            await interaction.response.send_message(
                f"No resources found{scope}. Add one with `/addresource`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(embed=embeds.resource_embed(found))

    @app_commands.command(name="addresource", description="Share a dev resource")
    @app_commands.describe(
        title="What it's called",
        url="Link, starting with https://",
        category="Topic, e.g. python",
        description="Optional one-liner",
    )
    @app_commands.checks.cooldown(1, 60.0)
    async def addresource(
        self,
        interaction: discord.Interaction,
        title: str,
        url: str,
        category: str,
        description: str | None = None,
    ):
        async with self.bot.session() as session:
            try:
                created = await add_resource(
                    session, title=title, url=url, category=category,
                    description=description, added_by=interaction.user.name,
                )
            except InvalidResource as exc:
                await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
                return

            embed = embeds.resource_embed(created)

        await interaction.response.send_message(content="✅ Added.", embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Resources(bot))
```

- [ ] **Step 2: Verify the cog loads**

Run: `./env/bin/python -c "
import asyncio
from champak.bot import ChampakBot
from champak.config import Config

cfg = Config(token='x', db_url='sqlite+aiosqlite:///:memory:', logging_level='WARNING',
             guild_id=None, admin_role_id=None, answer_cooldown_hours=24.0, max_attempts=3)

async def main():
    bot = ChampakBot(cfg)
    await bot.load_extension('champak.cogs.resources')
    print('commands:', sorted(c.name for c in bot.tree.get_commands()))
    await bot.engine.dispose()

asyncio.run(main())
"`

Expected: `commands: ['addresource', 'resource']`

- [ ] **Step 3: Commit**

```bash
git add champak/cogs/resources.py
git commit -m "feat: add resource commands with typed slash parameters"
```

---

### Task 13: Admin cog, CLI, docs, and final cleanup

**Files:**
- Create: `champak/cogs/admin.py`, `champak/cogs/meta.py`
- Rewrite: `admin.py`, `seed.py`, `README.md`, `QUICKSTART.md`
- Delete: root `bot.py`, root `utils.py`

**Interfaces:**
- Consumes: everything built so far.
- Produces: `/addquestion` (modal, admin-gated), `/help`, and the `admin.py` CLI verbs `stats`, `questions`, `resources`, `import`, `recompute-aura`, `reset`.

Discord modals allow **at most five** `TextInput` fields. The nine question fields are folded down to exactly five: title and description share one paragraph split on the first blank line, the four options arrive as one four-line textarea, and the correct letter and difficulty share one short field (`"B 4"`, or just `"B"` to default difficulty to 3). Adding a sixth input raises `ValueError` at class definition time — do not add one.

- [ ] **Step 1: Write the admin cog**

Create `champak/cogs/admin.py`:

```python
"""Admin-only question authoring."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from champak.db.import_questions import import_key_for
from champak.db.models import Question
from champak.ui import embeds

log = logging.getLogger(__name__)

VALID_OPTIONS = ("A", "B", "C", "D")


class AddQuestionModal(discord.ui.Modal, title="Add a question"):
    body = discord.ui.TextInput(
        label="Question",
        style=discord.TextStyle.paragraph,
        placeholder="The question. Leave a blank line to add extra detail below it.",
        max_length=1800,
    )
    category = discord.ui.TextInput(label="Category", placeholder="dsa", max_length=50)
    options = discord.ui.TextInput(
        label="Options (one per line, exactly 4)",
        style=discord.TextStyle.paragraph,
        placeholder="O(n)\nO(log n)\nO(n log n)\nO(1)",
        max_length=900,
    )
    # Discord allows five inputs at most, so the answer letter and the
    # difficulty share this one. Adding a sixth TextInput raises ValueError.
    answer = discord.ui.TextInput(
        label="Correct option + difficulty, e.g. B 4",
        placeholder="B 4",
        max_length=5,
    )
    explanation = discord.ui.TextInput(
        label="Explanation",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        title, _, description = str(self.body).partition("\n\n")
        title = title.strip()
        description = description.strip() or None

        lines = [line.strip() for line in str(self.options).splitlines() if line.strip()]
        if len(lines) != 4:
            await interaction.response.send_message(
                f"❌ Give exactly 4 options, one per line. I counted {len(lines)}.",
                ephemeral=True,
            )
            return

        parts = str(self.answer).strip().upper().split()
        letter = parts[0] if parts else ""
        if letter not in VALID_OPTIONS:
            await interaction.response.send_message(
                f"❌ Correct option must be A, B, C or D — got {self.answer!s}.",
                ephemeral=True,
            )
            return

        raw_difficulty = parts[1] if len(parts) > 1 else "3"
        if not raw_difficulty.isdigit() or not 1 <= int(raw_difficulty) <= 5:
            await interaction.response.send_message(
                f"❌ Difficulty must be 1-5 — got {raw_difficulty!r}.", ephemeral=True
            )
            return
        level = int(raw_difficulty)

        explanation = str(self.explanation).strip()
        if not explanation:
            await interaction.response.send_message(
                "❌ An explanation is required.", ephemeral=True
            )
            return

        question = Question(
            title=title,
            description=description,
            category=str(self.category).strip().lower(),
            difficulty=level,
            points=level * 10,
            option_a=lines[0], option_b=lines[1],
            option_c=lines[2], option_d=lines[3],
            correct_option=letter,
            explanation=explanation,
            asked_by=interaction.user.name,
            import_key=import_key_for(title),
        )

        async with self.bot.session() as session:
            session.add(question)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                log.exception("could not save question")
                await interaction.response.send_message(
                    "❌ Could not save that — an identical question may already exist.",
                    ephemeral=True,
                )
                return
            embed = embeds.question_embed(question, interaction.user.display_name)

        await interaction.response.send_message(
            content=f"✅ Added as question #{question.id}.", embed=embed, ephemeral=True
        )


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="addquestion", description="Add a question (admins only)")
    async def addquestion(self, interaction: discord.Interaction):
        if not self.bot.is_admin(interaction):
            await interaction.response.send_message(
                "That command is for admins only.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AddQuestionModal(self.bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
```

- [ ] **Step 2: Write the meta cog**

Create `champak/cogs/meta.py`:

```python
"""The /help command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from champak.ui import embeds


class Meta(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="What can this bot do?")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=embeds.help_embed(), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Meta(bot))
```

- [ ] **Step 3: Rewrite the CLI**

Replace `admin.py`:

```python
#!/usr/bin/env python3
"""Offline management for the Champak Chacha database."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

from champak.config import ConfigError, load_config
from champak.db.import_questions import DEFAULT_DIRECTORY, import_all
from champak.db.models import Answer, Base, Question, Resource, User
from champak.db.session import create_engine_for, init_db, make_session_factory
from champak.services.users import recompute_all


async def _count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def show_stats(session) -> None:
    print("\nDatabase")
    print("=" * 44)
    for label, model in (("Users", User), ("Questions", Question),
                         ("Resources", Resource), ("Answers", Answer)):
        print(f"  {label:<12} {await _count(session, model)}")

    rows = (await session.execute(
        select(Question.category, func.count())
        .group_by(Question.category).order_by(Question.category)
    )).all()
    if rows:
        print("\nQuestions by category")
        for category, total in rows:
            print(f"  {category:<24} {total}")

    top = (await session.execute(
        select(User).order_by(User.aura_points.desc()).limit(5)
    )).scalars().all()
    if top:
        print("\nTop 5 by aura")
        for i, user in enumerate(top, 1):
            print(f"  {i}. {user.username}: {user.aura_points}")


async def list_questions(session) -> None:
    rows = (await session.execute(
        select(Question).order_by(Question.id).limit(50)
    )).scalars().all()
    print(f"\nFirst {len(rows)} questions")
    for q in rows:
        flag = "" if q.is_active else " [inactive]"
        print(f"  #{q.id:<5} [{q.category}/d{q.difficulty}] {q.title[:60]}{flag}")


async def list_resources(session) -> None:
    rows = (await session.execute(select(Resource).order_by(Resource.id))).scalars().all()
    print(f"\n{len(rows)} resources")
    for r in rows:
        print(f"  #{r.id:<5} [{r.category}] {r.title} -> {r.url}")


async def recompute(session) -> None:
    changed = await recompute_all(session)
    if not changed:
        print("Cached counters already match the answer history.")
        return
    print(f"Repaired {len(changed)} users:")
    for discord_id, old, new in changed:
        print(f"  {discord_id}: {old} -> {new}")


async def run_import(session, argv: list[str]) -> None:
    directory = Path(argv[0]) if argv else DEFAULT_DIRECTORY
    stats = await import_all(session, directory)
    print(f"{stats.files} files -> {stats.created} created, {stats.updated} updated")


async def reset(engine) -> None:
    if input("Delete ALL data? Type 'yes': ").strip().lower() != "yes":
        print("Cancelled.")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db(engine)
    print("Database reset. Run 'python admin.py import' to reload questions.")


USAGE = """Champak Chacha admin

  python admin.py stats             Row counts and top users
  python admin.py questions         List the first 50 questions
  python admin.py resources         List every resource
  python admin.py import [dir]      Load the question bank (default data/questions)
  python admin.py recompute-aura    Rebuild cached counters from answers
  python admin.py reset             Drop every table (destructive)
"""


async def _main() -> int:
    if len(sys.argv) < 2:
        print(USAGE)
        return 0

    try:
        config = load_config()
    except ConfigError:
        # The CLI does not need a bot token, only a database.
        import os
        db_url = os.getenv("DB_URL", "sqlite:///app.db")
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    else:
        db_url = config.db_url

    engine = create_engine_for(db_url)
    await init_db(engine)
    factory = make_session_factory(engine)
    command, argv = sys.argv[1].lower(), sys.argv[2:]

    try:
        if command == "reset":
            await reset(engine)
            return 0

        async with factory() as session:
            actions = {
                "stats": lambda: show_stats(session),
                "questions": lambda: list_questions(session),
                "resources": lambda: list_resources(session),
                "recompute-aura": lambda: recompute(session),
                "import": lambda: run_import(session, argv),
            }
            action = actions.get(command)
            if action is None:
                print(f"Unknown command: {command}\n")
                print(USAGE)
                return 1
            await action()
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
```

- [ ] **Step 4: Rewrite the seed script**

Replace `seed.py`:

```python
#!/usr/bin/env python3
"""Seed starter resources. Questions come from `python admin.py import`."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import func, select

from champak.db.models import Resource
from champak.db.session import create_engine_for, init_db, make_session_factory
from champak.services.resources import add_resource

RESOURCES = [
    ("NeetCode 150", "https://neetcode.io/practice", "dsa",
     "A curated interview problem list with video walkthroughs."),
    ("Python Docs", "https://docs.python.org/3/", "python",
     "The official language and standard library reference."),
    ("MDN Web Docs", "https://developer.mozilla.org/", "javascript_typescript",
     "The reference for JavaScript, the DOM and web APIs."),
    ("System Design Primer", "https://github.com/donnemartin/system-design-primer",
     "system_design", "How large-scale systems are put together."),
    ("Refactoring Guru", "https://refactoring.guru/design-patterns", "oops_lld",
     "Design patterns explained with diagrams and code."),
    ("Twelve-Factor App", "https://12factor.net/", "backend_concepts",
     "Twelve principles for building maintainable services."),
]


async def _main() -> None:
    db_url = os.getenv("DB_URL", "sqlite:///app.db").replace(
        "sqlite:///", "sqlite+aiosqlite:///", 1
    )
    engine = create_engine_for(db_url)
    await init_db(engine)
    factory = make_session_factory(engine)

    added = 0
    async with factory() as session:
        for title, url, category, description in RESOURCES:
            exists = (await session.execute(
                select(func.count()).select_from(Resource).where(Resource.url == url)
            )).scalar_one()
            if exists:
                continue
            await add_resource(session, title=title, url=url, category=category,
                               description=description, added_by="seed")
            added += 1

    await engine.dispose()
    print(f"Seeded {added} new resources ({len(RESOURCES) - added} already present).")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 5: Delete the superseded root modules**

Root `bot.py` and `utils.py` are fully replaced by `champak/bot.py`, `champak/cogs/`, and `champak/ui/`.

```bash
git rm bot.py utils.py
```

- [ ] **Step 6: Rewrite the documentation**

Replace `README.md`:

````markdown
# Champak Chacha

A Discord quiz bot. 1,500 multiple-choice questions across DSA, Python,
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
python admin.py import           # 1500 questions from data/questions/
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
data/questions/   the 1500-question bank as JSON
tests/            pytest, service layer
```

The layer that matters is `services/`. It holds every rule and knows nothing
about Discord, so the scoring logic is testable without a gateway connection.

## Adding questions

Drop a JSON file into `data/questions/` and run `python admin.py import`.
Reimporting is idempotent — questions are matched on a hash of their text, so
existing rows are updated rather than duplicated.

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
````

Replace `QUICKSTART.md`:

````markdown
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
python admin.py import      # 1500 questions
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
`python admin.py stats` to confirm the count is 1500.

**Someone's aura looks wrong.** `python admin.py recompute-aura` rebuilds the
cached totals from the answer history.
````

- [ ] **Step 7: Run the whole test suite**

Run: `./env/bin/python -m pytest -v`
Expected: PASS, roughly 107 tests, zero failures

- [ ] **Step 8: Verify every cog loads together**

Run: `./env/bin/python -c "
import asyncio
from champak.bot import ChampakBot, COGS
from champak.config import Config

cfg = Config(token='x', db_url='sqlite+aiosqlite:///:memory:', logging_level='WARNING',
             guild_id=None, admin_role_id=None, answer_cooldown_hours=24.0, max_attempts=3)

async def main():
    bot = ChampakBot(cfg)
    for module in COGS:
        await bot.load_extension(module)
    names = sorted(c.name for c in bot.tree.get_commands())
    print('commands:', names)
    expected = ['addquestion','addresource','ask','aura','categories',
                'help','leaderboard','profile','resource']
    assert names == expected, f'expected {expected}, got {names}'
    assert bot.handle_answer.__qualname__ == 'Questions.handle_answer'

    from champak.cogs.admin import AddQuestionModal
    modal = AddQuestionModal(bot)
    fields = len(modal.children)
    assert fields <= 5, f'Discord allows 5 modal inputs, this has {fields}'
    print(f'modal inputs: {fields}/5')

    print('all 9 commands registered, answer handler wired')
    await bot.engine.dispose()

asyncio.run(main())
"`

Expected: all 9 commands listed, `modal inputs: 5/5`, then `all 9 commands registered, answer handler wired`

- [ ] **Step 9: Verify the old exploits are gone**

Run: `grep -rn "anubhav\|9999\|active_questions\|YOUR_DISCORD_ID" champak/ main.py admin.py seed.py || echo "CLEAN: no backdoor, no active_questions"`
Expected: `CLEAN: no backdoor, no active_questions`

Run: `test -f temp.py && echo "temp.py STILL PRESENT" || echo "temp.py gone"`
Expected: `temp.py gone`

- [ ] **Step 10: Rebuild the real database end to end**

```bash
rm -f app.db
./env/bin/python admin.py import
./env/bin/python seed.py
./env/bin/python admin.py stats
```

Expected: import reports `10 files -> 1500 created, 0 updated`; seed reports 6 resources; stats shows 1500 questions across 6 categories, 6 resources, 0 users, 0 answers.

- [ ] **Step 11: Commit**

```bash
git add champak/cogs/admin.py champak/cogs/meta.py admin.py seed.py README.md QUICKSTART.md
git rm --cached bot.py utils.py --ignore-unmatch
git commit -m "feat: add admin modal, CLI, and rewritten docs"
```

---

## Manual verification

Automated tests cover the service layer. These steps need a real Discord server and a real token.

- [ ] `/ask` posts a question with four working buttons.
- [ ] Clicking a button as a *different* user gets "That is not your question".
- [ ] A correct first answer awards full points and shows the explanation.
- [ ] A wrong answer shows attempts remaining and a relative retry time, and does **not** reveal the correct option.
- [ ] Answering the same question again immediately is refused with the cooldown message.
- [ ] `/leaderboard` reflects the aura just earned.
- [ ] `/addquestion` opens the modal for an admin and is refused for a non-admin.
- [ ] Restart the bot, then click a button on a question posted *before* the restart — it still works. This is the persistent-view check.
- [ ] `/ask` with an unknown category autocompletes to nothing and reports no questions.

## Known limitations

- Aura is a cached column, so it can drift from the answers table if a write path bypasses `submit_answer`. `admin.py recompute-aura` is the repair.
- The retry fallback in `pick_question` loads every attempted question for the user and checks eligibility in Python. At 1,500 questions per user this is fine; it would need a SQL rewrite at a much larger scale.
- Single server by design. Adding multi-server support means a `guild_id` migration across users, answers and the leaderboard.
