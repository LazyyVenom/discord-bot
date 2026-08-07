import pytest
from sqlalchemy import select

from champak.db.models import Resource
from champak.services.resources import (
    InvalidResource,
    add_resource,
    list_resource_categories,
    random_resource,
)


async def test_add_and_fetch(session):
    await add_resource(session, title="Docs", url="https://example.com",
                       category="python", description=None, added_by="anu")
    r = (await session.execute(select(Resource))).scalar_one()
    assert r.title == "Docs" and r.added_by == "anu" and r.upvotes == 0


async def test_rejects_non_http_url(session):
    with pytest.raises(InvalidResource, match="http"):
        await add_resource(session, title="X", url="javascript:alert(1)",
                           category="python", description=None, added_by="anu")


async def test_rejects_blank_title(session):
    with pytest.raises(InvalidResource, match="title"):
        await add_resource(session, title="   ", url="https://example.com",
                           category="python", description=None, added_by="anu")


async def test_rejects_blank_category(session):
    with pytest.raises(InvalidResource, match="category"):
        await add_resource(session, title="X", url="https://example.com",
                           category=" ", description=None, added_by="anu")


async def test_category_is_normalised(session):
    r = await add_resource(session, title="X", url="https://example.com",
                           category="  Python  ", description=None, added_by="anu")
    assert r.category == "python"


async def test_random_resource_none_when_empty(session):
    assert await random_resource(session, None) is None


async def test_random_resource_respects_category(session):
    await add_resource(session, title="A", url="https://a.com", category="dsa",
                       description=None, added_by="anu")
    py = await add_resource(session, title="B", url="https://b.com", category="python",
                            description=None, added_by="anu")
    got = await random_resource(session, "python")
    assert got.id == py.id


async def test_unknown_category_returns_none(session):
    await add_resource(session, title="A", url="https://a.com", category="dsa",
                       description=None, added_by="anu")
    assert await random_resource(session, "nope") is None


async def test_list_categories_sorted(session):
    for cat in ("python", "dsa", "dsa"):
        await add_resource(session, title=cat, url="https://x.com", category=cat,
                           description=None, added_by="anu")
    assert await list_resource_categories(session) == ["dsa", "python"]
