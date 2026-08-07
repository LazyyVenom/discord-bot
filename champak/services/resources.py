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
