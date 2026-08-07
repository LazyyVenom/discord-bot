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
