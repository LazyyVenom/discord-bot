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
