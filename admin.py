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
