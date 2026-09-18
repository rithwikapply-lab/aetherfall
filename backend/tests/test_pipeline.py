import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.continuity_guard import check_continuity
from app.agents.npc_memory import best_recall, retrieve_relevant, score_memory
from app.agents.pipeline import run_turn
from app.database import async_session_maker, init_db
from app.llm_client import LLMClient
from app.models import GameSession, InventoryItem, NPC, NPCMemoryEntry, StoryNode
from app.schemas import ContinuityResult


@pytest.mark.asyncio
async def test_npc_memory_scoring_and_recall():
    await init_db()

    async with async_session_maker() as session:
        npc = NPC(
            session_id="test-session",
            name="Kael",
            description="A hooded scout.",
            relationship_score=10,
        )
        session.add(npc)
        await session.flush()

        mem1 = NPCMemoryEntry(
            npc_id=npc.id,
            session_id="test-session",
            node_id="node-1",
            content="The traveler offered fresh rations and asked about the river bridge.",
            salience=9,
        )
        mem2 = NPCMemoryEntry(
            npc_id=npc.id,
            session_id="test-session",
            node_id="node-2",
            content="A pack of wolves howled across the distant ridgeline at midnight.",
            salience=3,
        )
        session.add_all([mem1, mem2])
        await session.commit()
        await session.refresh(npc, ["memories"])

    # 1. Zero lexical overlap -> score must be 0.0, best_recall returns None
    assert score_memory(mem1, "climb the slippery mountain cliffs") == 0.0
    assert best_recall(npc, "climb the slippery mountain cliffs") is None

    # 2. Overlapping words ("river bridge rations") -> high score and successful recall
    recall = best_recall(npc, "Cross the river bridge and share rations with the scout.")
    assert recall is not None
    recalled_mem, score = recall
    assert recalled_mem.id == mem1.id
    assert score > 0.3


@pytest.mark.asyncio
async def test_continuity_guard_tier1_short_circuit():
    """Prove that Tier 1 skips the LLM call entirely when no ancestor facts exist."""
    await init_db()

    class ExplosiveLLMClient(LLMClient):
        """Raises an exception if invoked, proving the Tier 1 short-circuit bypasses LLM calls."""
        async def generate_stream(self, *args, **kwargs):
            raise AssertionError("generate_stream should not be called!")

        async def generate_structured(self, *args, **kwargs):
            raise AssertionError("generate_structured should not be called in Tier 1 short-circuit!")

    async with async_session_maker() as session:
        game_session = GameSession(title="Continuity Test")
        session.add(game_session)
        await session.flush()

        # Root node with NO established facts
        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The gate creaks open.",
            facts=[],
        )
        session.add(root_node)
        await session.flush()

        # Child node whose parent chain has 0 facts
        child_node = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            narration="You walk down the damp corridor.",
            facts=[],
        )
        session.add(child_node)
        await session.commit()

        # Tier 1 check: Must return has_contradiction=False without invoking ExplosiveLLMClient
        result = await check_continuity(
            db_session=session,
            new_node=child_node,
            narration_text="You walk down the damp corridor.",
            llm_client=ExplosiveLLMClient(),
        )

        assert isinstance(result, ContinuityResult)
        assert result.has_contradiction is False
        assert "Tier 1 short-circuit" in result.reason


@pytest.mark.asyncio
async def test_pipeline_turn_execution_and_branching():
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="The Shattered Reach",
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

    # --------------------------------------------------------------------------
    # Turn 1: Search action -> verify items_gained, InventoryItem row created
    # --------------------------------------------------------------------------
    turn1 = await run_turn(session_id, "Search the mossy stone alcove for useful tools.")
    assert turn1.parent_id == root_node_id
    assert turn1.turn_number == 1
    assert len(turn1.state_delta.items_gained) >= 1
    assert turn1.hp == 100  # No damage from searching

    # Verify InventoryItem persisted to database
    async with async_session_maker() as session:
        stmt = select(InventoryItem).where(InventoryItem.session_id == session_id)
        items = (await session.execute(stmt)).scalars().all()
        assert len(items) >= 1
        assert items[0].name == turn1.state_delta.items_gained[0].name

        # Verify session.current_node_id updated
        s = await session.get(GameSession, session_id)
        assert s.current_node_id == turn1.node_id

    # --------------------------------------------------------------------------
    # Turn 2: Attack action -> verify negative hp_change, session hp updated
    # --------------------------------------------------------------------------
    turn2 = await run_turn(session_id, "Attack the river serpent surging from the water.")
    assert turn2.parent_id == turn1.node_id
    assert turn2.turn_number == 2
    assert turn2.state_delta.hp_change < 0
    assert turn2.hp < 100

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == turn2.hp
        assert s.current_node_id == turn2.node_id

    # --------------------------------------------------------------------------
    # Turn 3: Branching replay! Fork from root_node_id instead of turn2.node_id
    # --------------------------------------------------------------------------
    turn3_fork = await run_turn(
        session_id=session_id,
        action_text="Ask Kael for guidance along the western ridge.",
        from_node_id=root_node_id,  # Replay from earlier node
    )

    # CRITICAL VERIFICATION: new node's parent is root_node_id, NOT turn2.node_id
    assert turn3_fork.parent_id == root_node_id
    assert turn3_fork.turn_number == 1
    assert turn3_fork.node_id != turn1.node_id
    assert turn3_fork.node_id != turn2.node_id

    # Dialogue keyword check: NPC delta and memory created
    assert len(turn3_fork.state_delta.npc_relationship_deltas) >= 1
    assert turn3_fork.state_delta.npc_relationship_deltas[0].npc_name == "Kael"

    # Confirm original branch (turn1, turn2) remains completely intact in the tree
    async with async_session_maker() as session:
        t1 = await session.get(StoryNode, turn1.node_id)
        t2 = await session.get(StoryNode, turn2.node_id)
        t3 = await session.get(StoryNode, turn3_fork.node_id)
        assert t1 is not None
        assert t2 is not None
        assert t3 is not None

        # Verify tree hierarchy: root has two distinct children (turn1 and turn3_fork)
        root = await session.get(StoryNode, root_node_id, options=[selectinload(StoryNode.children)])
        child_ids = {c.id for c in root.children}
        assert turn1.node_id in child_ids
        assert turn3_fork.node_id in child_ids
        assert len(child_ids) == 2

        # Session current_node_id now points to the new active fork (turn3_fork)
        s = await session.get(GameSession, session_id)
        assert s.current_node_id == turn3_fork.node_id
