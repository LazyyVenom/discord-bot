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
    candidates = (
        await session.execute(base.where(Question.id.in_(attempted_ids)))
    ).scalars().all()
    if not candidates:
        return QuestionPick(question=None, reason="empty")

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
        raise ValueError(
            f"chosen option must be one of {VALID_OPTIONS}, got {chosen!r}"
        )

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
