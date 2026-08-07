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
