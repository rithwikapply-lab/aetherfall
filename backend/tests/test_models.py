import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session_maker, init_db
from app.models import (
    GameSession,
    InventoryItem,
    NPC,
    NPCMemoryEntry,
    Quest,
    StoryNode,
)


@pytest.mark.asyncio
async def test_data_model_lifecycle_and_eager_loading():
    # 1. Initialize schema
    await init_db()

    # 2. Create session, tree nodes, items, quests, NPC, and memory
    async with async_session_maker() as session:
        game_session = GameSession(
            title="The Chronicles of Aetherfall",
            chapter="Chapter 1: The Drowned Road",
            hp=95,
            max_hp=100,
            focus=45,
            max_focus=50,
            location="The Sunken Crossroads",
            mood="Wary",
        )
        session.add(game_session)
        await session.flush()

        # Root Story Node (parent_id = None, turn_number = 0)
        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            player_action=None,
            narration="Rain lashes the mud-slicked stones of the crossroads.",
            location="The Sunken Crossroads",
            facts=["the bridge is out", "Kael is missing an eye"],
        )
        session.add(root_node)
        await session.flush()

        # Set session current node to root
        game_session.current_node_id = root_node.id

        # Child Story Node (fork / next turn under root)
        child_node = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            player_action="Approach the hooded figure sheltering under the ruined archway.",
            narration="Kael raises his lantern, the scarred side of his face cast in amber light.",
            location="The Ruined Archway",
            facts=["Kael carries a lantern of cold blue fire"],
        )
        session.add(child_node)
        await session.flush()

        # Inventory item
        item = InventoryItem(
            session_id=game_session.id,
            name="Rusted Iron Key",
            description="Found lodged in the timbers of the old gatehouse.",
            acquired_at_node_id=child_node.id,
        )
        session.add(item)

        # Quest
        quest = Quest(
            session_id=game_session.id,
            title="Cross the Drowned Valley",
            status="active",
            description="Find a way across the flooded chasm now that the bridge is out.",
            updated_at_node_id=child_node.id,
        )
        session.add(quest)

        # NPC
        npc = NPC(
            session_id=game_session.id,
            name="Kael",
            description="A cynical scout stranded on the north bank.",
            relationship_score=25,
        )
        session.add(npc)
        await session.flush()

        # NPC Memory Entry
        memory = NPCMemoryEntry(
            npc_id=npc.id,
            session_id=game_session.id,
            node_id=child_node.id,
            content="The traveler approached slowly and without weapon drawn.",
            salience=8,
        )
        session.add(memory)

        await session.commit()
        npc_id = npc.id
        root_node_id = root_node.id
        child_node_id = child_node.id

    # 3. Query NPC with selectinload in a new session
    async with async_session_maker() as query_session:
        stmt = (
            select(NPC)
            .where(NPC.id == npc_id)
            .options(selectinload(NPC.memories))
        )
        result = await query_session.execute(stmt)
        loaded_npc = result.scalar_one()

    # 4. Outside session context: verify memories are accessible without MissingGreenlet
    assert len(loaded_npc.memories) == 1
    loaded_mem = loaded_npc.memories[0]
    assert loaded_mem.content == "The traveler approached slowly and without weapon drawn."
    assert loaded_mem.salience == 8
    assert loaded_mem.node_id == child_node_id

    # 5. Verify relationship_label logic
    assert loaded_npc.relationship_label == "Friendly"

    # Test all sentiment boundary tiers
    loaded_npc.relationship_score = -75
    assert loaded_npc.relationship_label == "Hostile"

    loaded_npc.relationship_score = -25
    assert loaded_npc.relationship_label == "Wary"

    loaded_npc.relationship_score = 0
    assert loaded_npc.relationship_label == "Neutral"

    loaded_npc.relationship_score = 30
    assert loaded_npc.relationship_label == "Friendly"

    loaded_npc.relationship_score = 80
    assert loaded_npc.relationship_label == "Devoted"

    # 6. Verify StoryNode tree parent/child relationship
    async with async_session_maker() as node_session:
        stmt = (
            select(StoryNode)
            .where(StoryNode.id == root_node_id)
            .options(selectinload(StoryNode.children))
        )
        result = await node_session.execute(stmt)
        loaded_root = result.scalar_one()

        assert len(loaded_root.children) == 1
        assert loaded_root.children[0].id == child_node_id
        assert loaded_root.facts == ["the bridge is out", "Kael is missing an eye"]


@pytest.mark.asyncio
async def test_game_session_game_over_and_turn_count_lifecycle():
    await init_db()

    async with async_session_maker() as session:
        # Default initialization
        gs = GameSession(title="Game Over Test Session")
        session.add(gs)
        await session.commit()
        session_id = gs.id

    async with async_session_maker() as session:
        loaded = await session.get(GameSession, session_id)
        assert loaded.max_hp == 100
        assert loaded.max_focus == 50
        assert loaded.hp == 100
        assert loaded.focus == 50
        assert loaded.turn_count == 0
        assert loaded.is_game_over is False
        assert loaded.game_over_reason is None
        assert loaded.game_over_summary is None

        # Transition to game-over state
        loaded.is_game_over = True
        loaded.game_over_reason = "death"
        loaded.game_over_summary = "The traveler was dragged into the black river depths."
        loaded.turn_count = 7
        await session.commit()

    async with async_session_maker() as session:
        updated = await session.get(GameSession, session_id)
        assert updated.is_game_over is True
        assert updated.game_over_reason == "death"
        assert updated.game_over_summary == "The traveler was dragged into the black river depths."
        assert updated.turn_count == 7

