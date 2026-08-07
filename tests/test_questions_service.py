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
