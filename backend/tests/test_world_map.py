"""Tests for the World Map API endpoint (GET /api/sessions/{id}/map).

Covers:
1. Nodes and edges render correctly from a multi-location session.
2. Chapter-based coloring is correct for a multi-chapter session.
3. A session with only a single visited location doesn't break the layout algorithm.
4. Mentioned-but-unvisited locations render with visited=False (distinct from visited nodes).
"""

import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import GameSession, StoryNode
from app.database import async_session_maker


def make_session_id() -> str:
    return str(uuid.uuid4())


def make_node_id() -> str:
    return str(uuid.uuid4())


async def create_map_session(
    db: AsyncSession,
    chapter_number: int = 1,
    completed_chapters: list[int] | None = None,
    location: str = "The Sunken Crossroads",
) -> GameSession:
    """Seed a minimal GameSession for world-map tests."""
    session = GameSession(
        id=make_session_id(),
        title="Map Test Campaign",
        chapter_number=chapter_number,
        completed_chapters=completed_chapters or [],
        hp=100,
        max_hp=100,
        focus=50,
        max_focus=50,
        location=location,
        mood="Wary",
    )
    db.add(session)
    await db.flush()
    return session


async def create_story_node(
    db: AsyncSession,
    session_id: str,
    parent_id: str | None,
    turn_number: int,
    location: str,
    narration: str = "The mist hangs low over the sodden ground.",
    locations_mentioned: list[str] | None = None,
) -> StoryNode:
    """Seed a StoryNode with optional locations_mentioned."""
    node = StoryNode(
        id=make_node_id(),
        session_id=session_id,
        parent_id=parent_id,
        turn_number=turn_number,
        player_action=None if turn_number == 0 else f"Move to {location}",
        narration=narration,
        location=location,
        facts=[],
        locations_mentioned=locations_mentioned or [],
    )
    db.add(node)
    await db.flush()
    return node


@pytest.mark.asyncio
async def test_world_map_nodes_and_edges_correct():
    """Nodes and edges render correctly from a 3-location session.

    Session path: Crossroads -> Gatehouse -> Salt Marsh
    Expected: 3 visited nodes, 2 directed edges.
    """
    async with async_session_maker() as db:
        session = await create_map_session(db, location="Salt Marsh")

        root = await create_story_node(
            db, session.id, None, 0, "The Sunken Crossroads",
            narration="Rain lashes the crossroads.",
        )
        node1 = await create_story_node(
            db, session.id, root.id, 1, "Ruined Gatehouse",
            narration="The gatehouse looms against the grey sky.",
        )
        node2 = await create_story_node(
            db, session.id, node1.id, 2, "Salt Marsh",
            narration="Brine and reed choke the air of the marsh.",
        )

        session.current_node_id = node2.id
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/sessions/{session.id}/map")

    assert resp.status_code == 200
    data = resp.json()

    node_names = {n["name"] for n in data["nodes"]}
    assert "The Sunken Crossroads" in node_names
    assert "Ruined Gatehouse" in node_names
    assert "Salt Marsh" in node_names
    for n in data["nodes"]:
        assert n["visited"] is True, f"{n['name']} should be visited"

    assert len(data["edges"]) == 2
    edge_pairs = {(e["source_id"], e["target_id"]) for e in data["edges"]}
    assert ("the-sunken-crossroads", "ruined-gatehouse") in edge_pairs
    assert ("ruined-gatehouse", "salt-marsh") in edge_pairs

    current_nodes = [n for n in data["nodes"] if n["is_current"]]
    assert len(current_nodes) == 1
    assert current_nodes[0]["name"] == "Salt Marsh"


@pytest.mark.asyncio
async def test_world_map_chapter_coloring_multi_chapter():
    """Chapter-based coloring assigns correct chapter numbers across two chapters."""
    async with async_session_maker() as db:
        session = await create_map_session(
            db,
            chapter_number=2,
            completed_chapters=[1],
            location="The Ghost-Catcher's Lodge",
        )

        root = await create_story_node(db, session.id, None, 0, "The Sunken Crossroads")
        n1 = await create_story_node(db, session.id, root.id, 1, "Ruined Gatehouse")
        n2 = await create_story_node(db, session.id, n1.id, 2, "The Ghost-Catcher's Lodge")
        n3 = await create_story_node(db, session.id, n2.id, 3, "The Ghost-Catcher's Lodge")

        session.current_node_id = n3.id
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/sessions/{session.id}/map")

    assert resp.status_code == 200
    data = resp.json()

    by_name = {n["name"]: n for n in data["nodes"]}
    assert by_name["The Sunken Crossroads"]["chapter_number"] == 1
    assert by_name["Ruined Gatehouse"]["chapter_number"] == 1
    assert by_name["The Ghost-Catcher's Lodge"]["chapter_number"] == 2


@pytest.mark.asyncio
async def test_world_map_single_location_no_crash():
    """A session with only one visited location returns 1 node and 0 edges."""
    async with async_session_maker() as db:
        session = await create_map_session(db, location="The Sunken Crossroads")

        root = await create_story_node(
            db, session.id, None, 0, "The Sunken Crossroads",
            narration="The crossroads are flooded.",
        )
        session.current_node_id = root.id
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/sessions/{session.id}/map")

    assert resp.status_code == 200
    data = resp.json()

    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["name"] == "The Sunken Crossroads"
    assert data["nodes"][0]["visited"] is True
    assert data["nodes"][0]["is_current"] is True
    assert len(data["edges"]) == 0


@pytest.mark.asyncio
async def test_world_map_mentioned_unvisited_renders_distinct():
    """Mentioned-but-unvisited locations appear with visited=False and no edges."""
    async with async_session_maker() as db:
        session = await create_map_session(db, location="The Sunken Crossroads")

        root = await create_story_node(
            db, session.id, None, 0, "The Sunken Crossroads",
            narration="The scout warns that Bone Quay is fully submerged.",
            locations_mentioned=["Bone Quay"],
        )
        session.current_node_id = root.id
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/sessions/{session.id}/map")

    assert resp.status_code == 200
    data = resp.json()

    by_name = {n["name"]: n for n in data["nodes"]}
    assert "The Sunken Crossroads" in by_name
    assert "Bone Quay" in by_name, "Mentioned location must appear in map nodes"

    assert by_name["The Sunken Crossroads"]["visited"] is True
    assert by_name["Bone Quay"]["visited"] is False
    assert by_name["Bone Quay"]["is_current"] is False

    edge_targets = {e["target_id"] for e in data["edges"]}
    assert "bone-quay" not in edge_targets
