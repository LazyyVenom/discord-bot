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
