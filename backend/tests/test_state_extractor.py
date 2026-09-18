import pytest
from sqlalchemy import select

from app.agents.state_extractor import apply_state_delta, extract_state_delta
from app.database import async_session_maker, init_db
from app.models import GameSession, InventoryItem, NPC, NPCMemoryEntry, StoryNode
from app.schemas import ItemGain, NPCRelationshipDelta, StateDelta


@pytest.mark.asyncio
async def test_extract_state_delta_combat_action():
    session = GameSession(hp=100, max_hp=100, mood="Wary", location="The Sunken Crossroads")
    action_text = "Attack the feral bog hound with a sharpened spear."
    narration_text = "The spear strikes true, but the hound snaps at your arm, tearing flesh before collapsing."

    delta = await extract_state_delta(
        action_text=action_text,
        narration_text=narration_text,
        session=session,
    )

    assert isinstance(delta, StateDelta)
    assert delta.hp_change < 0
    assert -15 <= delta.hp_change <= -1
    assert len(delta.items_gained) == 0
    assert len(delta.npc_relationship_deltas) == 0


@pytest.mark.asyncio
async def test_extract_state_delta_search_action():
    session = GameSession(hp=100, max_hp=100, mood="Wary", location="The Sunken Crossroads")
    action_text = "Search the muddy cargo wagon for salvage."
    narration_text = "Under a sodden tarp, your fingers brush against a cold metallic object."

    delta = await extract_state_delta(
        action_text=action_text,
        narration_text=narration_text,
        session=session,
    )

    assert isinstance(delta, StateDelta)
    assert len(delta.items_gained) >= 1
    assert delta.items_gained[0].name != ""
    assert delta.hp_change == 0
    assert len(delta.npc_relationship_deltas) == 0


@pytest.mark.asyncio
async def test_extract_state_delta_dialogue_action():
    session = GameSession(hp=100, max_hp=100, mood="Wary", location="The Sunken Crossroads")
    action_text = "Ask Kael if he knows where the river is shallow enough to ford."
    narration_text = "Kael pauses, his one good eye narrowing as he studies your sodden map."

    delta = await extract_state_delta(
        action_text=action_text,
        narration_text=narration_text,
        session=session,
    )

    assert isinstance(delta, StateDelta)
    assert len(delta.npc_relationship_deltas) >= 1
    npc_delta = delta.npc_relationship_deltas[0]
    assert npc_delta.npc_name == "Kael"
    assert npc_delta.delta > 0
    assert len(npc_delta.memory_note) > 0
    assert delta.hp_change == 0
    assert len(delta.items_gained) == 0


@pytest.mark.asyncio
async def test_apply_state_delta_to_database():
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="State Delta DB Test",
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Crossroads",
            mood="Wary",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Opening scene.",
            location="The Sunken Crossroads",
        )
        session.add(root_node)
        await session.flush()
        game_session.current_node_id = root_node.id

        # Pre-seed NPC Kael
        kael = NPC(
            session_id=game_session.id,
            name="Kael",
            description="Scout.",
            relationship_score=0,
        )
        session.add(kael)
        await session.commit()
        session_id = game_session.id
        root_id = root_node.id

    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        root_node = await session.get(StoryNode, root_id)

        delta = StateDelta(
            hp_change=-12,
            focus_change=-5,
            location="The Abandoned Sluice",
            mood="Grim",
            items_gained=[ItemGain(name="Iron Crowbar", description="Stout tool for prying doors.")],
            items_lost=[],
            npc_relationship_deltas=[
                NPCRelationshipDelta(
                    npc_name="Kael",
                    delta=15,
                    memory_note="The traveler helped unjam the iron sluice wheel.",
                )
            ],
            facts_established=["the sluice gates are rusted open"],
        )

        new_node = await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta,
            parent_node=root_node,
            action_text="Force open the sluice wheel.",
            narration_text="With a metallic screech, the wheel turns, venting dark water.",
        )
        await session.commit()
        new_node_id = new_node.id

    # Verify persistent DB state mutations
    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == 88
        assert s.focus == 45
        assert s.location == "The Abandoned Sluice"
        assert s.mood == "Grim"
        assert s.current_node_id == new_node_id

        # Verify StoryNode
        node = await session.get(StoryNode, new_node_id)
        assert node.parent_id == root_id
        assert node.turn_number == 1
        assert node.facts == ["the sluice gates are rusted open"]

        # Verify InventoryItem row created
        stmt = select(InventoryItem).where(InventoryItem.session_id == session_id)
        items = (await session.execute(stmt)).scalars().all()
        assert len(items) == 1
        assert items[0].name == "Iron Crowbar"
        assert items[0].acquired_at_node_id == new_node_id

        # Verify NPC affinity and memory entry
        stmt_npc = select(NPC).where(NPC.session_id == session_id).where(NPC.name == "Kael")
        npc = (await session.execute(stmt_npc)).scalar_one()
        assert npc.relationship_score == 15
        assert npc.relationship_label == "Friendly"

        stmt_mem = select(NPCMemoryEntry).where(NPCMemoryEntry.npc_id == npc.id)
        memories = (await session.execute(stmt_mem)).scalars().all()
        assert len(memories) == 1
        assert memories[0].content == "The traveler helped unjam the iron sluice wheel."
        assert memories[0].node_id == new_node_id
