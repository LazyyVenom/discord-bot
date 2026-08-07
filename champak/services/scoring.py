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
