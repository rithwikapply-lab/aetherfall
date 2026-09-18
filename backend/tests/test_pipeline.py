import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.pipeline import run_turn
from app.database import async_session_maker
from app.models import GameSession, InventoryItem, StoryNode


@pytest.mark.asyncio
async def test_pipeline_turn_execution_keyword_flow():
    """Verify standard linear progression and keyword-sensitive delta handling:
    search action adds item to inventory, attack action applies combat damage.
    """
    async with async_session_maker() as session:
        game_session = GameSession(
            title="Linear Flow Test",
            chapter="Chapter 1: The Sunken Gate",
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Gate",
            mood="Wary",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Dark waters lap against the mossy flagstones of the gate.",
            location="The Sunken Gate",
            facts=["the bridge is out"],
        )
        session.add(root_node)
        await session.flush()

        game_session.current_node_id = root_node.id
        await session.commit()
        session_id = game_session.id
        root_node_id = root_node.id

    # Turn 1: Search keyword -> item gained and saved to DB (per-turn attrition applies: -1 HP, -2 Focus)
    turn1 = await run_turn(session_id, "Search the mossy stone alcove for salvage.")
    assert turn1.parent_id == root_node_id
    assert turn1.turn_number == 1
    assert len(turn1.state_delta.items_gained) >= 1
    assert turn1.hp == 99
    assert turn1.focus == 48

    async with async_session_maker() as session:
        stmt = select(InventoryItem).where(InventoryItem.session_id == session_id)
        items = (await session.execute(stmt)).scalars().all()
        assert len(items) >= 1
        assert items[0].name == turn1.state_delta.items_gained[0].name

        s = await session.get(GameSession, session_id)
        assert s.current_node_id == turn1.node_id

    # Turn 2: Attack keyword -> damage applied, hp reduced
    turn2 = await run_turn(session_id, "Attack the river serpent lunging from the marsh.")
    assert turn2.parent_id == turn1.node_id
    assert turn2.turn_number == 2
    assert turn2.state_delta.hp_change < 0
    assert turn2.hp < 99

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == turn2.hp
        assert s.current_node_id == turn2.node_id


@pytest.mark.asyncio
async def test_replay_from_earlier_node_creates_a_branch():
    """Verify replaying from an earlier ancestor node creates a new child branch.

    Setup: Seed a session with 3 sequential turns:
        root (turn 0) -> node1 (turn 1) -> node2 (turn 2) -> node3 (turn 3)
    with current_node_id pointing at node3.

    Action: Call run_turn with from_node_id=node1.id.

    Assertions:
    (a) The new node's parent_id is node1.id, NOT node3.id.
    (b) node3's narration, facts, and parent_id are completely untouched.
    (c) The session's current_node_id now points at the new node, not node3.
    (d) The tree hierarchy correctly shows node1 has two distinct children.
    """
    node3_narration = "You step cautiously into the sunken crypt, your torch revealing carved gargoyles."
    node3_facts = ["the crypt entrance is guarded by two granite gargoyles"]

    async with async_session_maker() as session:
        game_session = GameSession(
            title="Branching Verification Campaign",
            chapter="Chapter 1: The Crypts",
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Ancient Crypts",
            mood="Grim",
        )
        session.add(game_session)
        await session.flush()

        # Root: Turn 0
        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The iron gates stand rusted ajar.",
            facts=["the gates are rusted open"],
        )
        session.add(root_node)
        await session.flush()

        # Node 1: Turn 1 (child of root)
        node1 = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            player_action="Walk past the rusted gates into the courtyard.",
            narration="You cross the overgrown courtyard littered with fallen pillars.",
            facts=["the courtyard pillars are shattered"],
        )
        session.add(node1)
        await session.flush()

        # Node 2: Turn 2 (child of node1)
        node2 = StoryNode(
            session_id=game_session.id,
            parent_id=node1.id,
            turn_number=2,
            player_action="Descend the spiral stone stairs.",
            narration="The damp stairs spiral downward into darkness.",
            facts=["the stairs are slick with black mold"],
        )
        session.add(node2)
        await session.flush()

        # Node 3: Turn 3 (child of node2 - active leaf)
        node3 = StoryNode(
            session_id=game_session.id,
            parent_id=node2.id,
            turn_number=3,
            player_action="Push open the heavy bronze crypt door.",
            narration=node3_narration,
            facts=list(node3_facts),
        )
        session.add(node3)
        await session.flush()

        # Point session at leaf node3
        game_session.current_node_id = node3.id
        await session.commit()

        session_id = game_session.id
        node1_id = node1.id
        node2_id = node2.id
        node3_id = node3.id

    # --------------------------------------------------------------------------
    # Replay action: Fork from node1 instead of continuing from leaf node3
    # --------------------------------------------------------------------------
    fork_result = await run_turn(
        session_id=session_id,
        action_text="Search the overgrown courtyard for a hidden entrance.",
        from_node_id=node1_id,
    )

    # --------------------------------------------------------------------------
    # Assertion (a): new node's parent_id MUST be node1.id, NOT node3.id
    # --------------------------------------------------------------------------
    assert fork_result.parent_id == node1_id, (
        f"Expected new branch node parent to be node1 ({node1_id}), "
        f"but got {fork_result.parent_id}. Pipeline failed to honor from_node_id!"
    )
    assert fork_result.parent_id != node3_id, (
        "New node was erroneously parented to current leaf (node3) instead of from_node_id!"
    )
    assert fork_result.turn_number == 2, (
        f"New branch from turn 1 should be turn 2, got {fork_result.turn_number}"
    )
    assert fork_result.node_id != node2_id
    assert fork_result.node_id != node3_id

    # --------------------------------------------------------------------------
    # Assertion (b): node3's narration/facts/parent are completely untouched
    # --------------------------------------------------------------------------
    async with async_session_maker() as session:
        refreshed_node3 = await session.get(StoryNode, node3_id)
        assert refreshed_node3 is not None
        assert refreshed_node3.narration == node3_narration
        assert refreshed_node3.facts == node3_facts
        assert refreshed_node3.parent_id == node2_id
        assert refreshed_node3.turn_number == 3

        # Also confirm node2 is untouched
        refreshed_node2 = await session.get(StoryNode, node2_id)
        assert refreshed_node2 is not None
        assert refreshed_node2.parent_id == node1_id

    # --------------------------------------------------------------------------
    # Assertion (c): session's current_node_id now points at the new branch node
    # --------------------------------------------------------------------------
    async with async_session_maker() as session:
        refreshed_session = await session.get(GameSession, session_id)
        assert refreshed_session.current_node_id == fork_result.node_id
        assert refreshed_session.current_node_id != node3_id

    # --------------------------------------------------------------------------
    # Assertion (d): tree hierarchy shows node1 has exactly 2 distinct children
    # --------------------------------------------------------------------------
    async with async_session_maker() as session:
        node1_refreshed = await session.get(
            StoryNode,
            node1_id,
            options=[selectinload(StoryNode.children)],
        )
        child_ids = {c.id for c in node1_refreshed.children}
        assert len(child_ids) == 2
        assert node2_id in child_ids
        assert fork_result.node_id in child_ids


@pytest.mark.asyncio
async def test_pipeline_rejects_action_on_game_over_session():
    """Verify run_turn raises ValueError when invoked on an ended session."""
    async with async_session_maker() as session:
        game_session = GameSession(
            title="Terminated Session",
            hp=0,
            max_hp=100,
            focus=0,
            max_focus=50,
            is_game_over=True,
            game_over_reason="death",
            game_over_summary="Fell in battle.",
            location="The Sunken Crossroads",
            mood="Grim",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Opening.",
            location="The Sunken Crossroads",
        )
        session.add(root_node)
        await session.flush()
        game_session.current_node_id = root_node.id
        await session.commit()
        session_id = game_session.id

    with pytest.raises(ValueError, match="has already ended"):
        await run_turn(session_id, "Strike the shadow again.")
