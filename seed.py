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
