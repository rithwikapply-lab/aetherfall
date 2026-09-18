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
        # Starting 100 HP - 12 delta - 1 attrition = 87
        assert s.hp == 87
        # Starting 50 Focus - 5 delta - 2 attrition = 43
        assert s.focus == 43
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


@pytest.mark.asyncio
async def test_apply_state_delta_attrition_and_clamping():
    """Verify deterministic per-turn attrition (-1 HP, -2 Focus) and clamping to [0, max]."""
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="Attrition Test",
            hp=10,
            max_hp=100,
            focus=10,
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
        await session.commit()
        session_id = game_session.id
        root_id = root_node.id

    # Case 1: Passive action (hp_delta=0, focus_delta=0) -> attrition applies (-1 HP, -2 Focus)
    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        root_node = await session.get(StoryNode, root_id)

        delta_passive = StateDelta(
            hp_delta=0,
            focus_delta=0,
            hp_delta_reason="No injury sustained",
            focus_delta_reason="No strain",
        )
        await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta_passive,
            parent_node=root_node,
            action_text="Wait quietly.",
            narration_text="Time passes in the damp drizzle.",
        )
        await session.commit()

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == 9  # 10 - 1
        assert s.focus == 8  # 10 - 2
        assert s.is_game_over is False

    # Case 2: Over-healing clamped to max_hp and max_focus
    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        curr_node = await session.get(StoryNode, game_session.current_node_id)

        delta_heal = StateDelta(
            hp_delta=200,
            focus_delta=200,
            hp_delta_reason="Divine fountain healing",
            focus_delta_reason="Ethereal rejuvenation",
        )
        await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta_heal,
            parent_node=curr_node,
            action_text="Drink deeply from the divine font.",
            narration_text="Pure golden luminescence floods your veins.",
        )
        await session.commit()

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == 100  # Clamped to max_hp (100)
        assert s.focus == 50  # Clamped to max_focus (50)
        assert s.is_game_over is False


@pytest.mark.asyncio
async def test_game_over_death_when_hp_reaches_zero():
    """Verify reaching 0 HP sets is_game_over=True, game_over_reason='death', and writes summary."""
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="Death Test",
            hp=5,
            max_hp=100,
            focus=40,
            max_focus=50,
            location="The Serpent Trench",
            mood="Desperate",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The trench walls shudder.",
            location="The Serpent Trench",
        )
        session.add(root_node)
        await session.flush()
        game_session.current_node_id = root_node.id
        await session.commit()
        session_id = game_session.id
        root_id = root_node.id

    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        root_node = await session.get(StoryNode, root_id)

        # Fatal damage: -10 HP + (-1 attrition) exceeds remaining 5 HP -> clamped to 0
        delta = StateDelta(
            hp_delta=-10,
            focus_delta=0,
            hp_delta_reason="Crushed by a falling boulder",
        )
        await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta,
            parent_node=root_node,
            action_text="Brace against the falling rocks.",
            narration_text="The ceiling gives way, burying you in stone.",
        )
        await session.commit()

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == 0
        assert s.is_game_over is True
        assert s.game_over_reason == "death"
        assert s.game_over_summary is not None
        assert len(s.game_over_summary) > 0


@pytest.mark.asyncio
async def test_game_over_collapse_when_focus_reaches_zero():
    """Verify reaching 0 Focus (while HP > 0) sets game_over_reason='collapse'."""
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="Collapse Test",
            hp=50,
            max_hp=100,
            focus=5,
            max_focus=50,
            location="The Whispering Vaults",
            mood="Terrified",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Eldritch whispers fill the vault.",
            location="The Whispering Vaults",
        )
        session.add(root_node)
        await session.flush()
        game_session.current_node_id = root_node.id
        await session.commit()
        session_id = game_session.id
        root_id = root_node.id

    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        root_node = await session.get(StoryNode, root_id)

        # Severe psychic strain: -10 Focus + (-2 attrition) reduces Focus from 5 to 0
        delta = StateDelta(
            hp_delta=0,
            focus_delta=-10,
            focus_delta_reason="Mind shattered by the ancient entity's gaze",
        )
        await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta,
            parent_node=root_node,
            action_text="Peer into the void mirror.",
            narration_text="Unspeakable visions assault your consciousness.",
        )
        await session.commit()

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.focus == 0
        assert s.hp == 49  # 50 - 1 attrition
        assert s.is_game_over is True
        assert s.game_over_reason == "collapse"
        assert s.game_over_summary is not None
        assert len(s.game_over_summary) > 0


@pytest.mark.asyncio
async def test_game_over_hp_priority_when_both_reach_zero():
    """Verify HP takes priority if both HP and Focus reach 0 in the same turn."""
    await init_db()

    async with async_session_maker() as session:
        game_session = GameSession(
            title="Dual Zero Priority Test",
            hp=1,
            max_hp=100,
            focus=2,
            max_focus=50,
            location="The Abyssal Rift",
            mood="Doomed",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The rift opens wide.",
            location="The Abyssal Rift",
        )
        session.add(root_node)
        await session.flush()
        game_session.current_node_id = root_node.id
        await session.commit()
        session_id = game_session.id
        root_id = root_node.id

    async with async_session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        root_node = await session.get(StoryNode, root_id)

        # Passive turn: 1 HP - 1 attrition = 0, 2 Focus - 2 attrition = 0
        delta = StateDelta(hp_delta=0, focus_delta=0)
        await apply_state_delta(
            db_session=session,
            session=game_session,
            delta=delta,
            parent_node=root_node,
            action_text="Succumb to the void.",
            narration_text="Darkness swallows everything.",
        )
        await session.commit()

    async with async_session_maker() as session:
        s = await session.get(GameSession, session_id)
        assert s.hp == 0
        assert s.focus == 0
        assert s.is_game_over is True
        # HP priority rule: must be death, NOT collapse
        assert s.game_over_reason == "death"
        assert s.game_over_summary is not None
