"""State-Extraction Agent for Aetherfall.

Extracts structured world-state mutations (StateDelta) from completed turn
narration and player actions using forced schema generation, then commits
atomic database updates to GameSession, StoryNode, InventoryItem, and NPC tables.
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.llm_client import LLMClient, get_llm_client
from app.models import GameSession, InventoryItem, NPC, NPCMemoryEntry, Quest, StoryNode
from app.schemas import StateDelta

STATE_EXTRACTOR_SYSTEM_PROMPT = """You are the World State Extraction Agent for Aetherfall, a dark fantasy narrative RPG.
Your job is to read the player's action and the resulting narrative prose, and extract precise, structured state changes.

Follow these resource and reasoning instructions strictly:
1. Resource Deltas & Reasoning:
- hp_delta: Integer health point change resulting from physical events this turn (default 0).
  * Harm & Hazards: Negative if the player suffered physical wounds, crushing trauma, burns, poison, or environmental hazards.
  * Aggression & Recklessness: Overextending in melee, recklessly charging armed enemies without defense, or uncontrolled aggressive actions expose the player to retaliatory damage (negative).
  * Recovery: Positive if the player explicitly rested in safety, bandaged wounds, or consumed restorative medicine.
- hp_delta_reason: A concise sentence explaining the physical justification for hp_delta based on harm, aggression, hazards, or recovery. Set to null if hp_delta is 0.
- focus_delta: Integer focus point change resulting from mental or magical exertion this turn (default 0).
  * Mental Strain & Sorcery: Negative if the player channeled magic, deciphered ancient runes, maintained intense concentration, or endured psychological horror.
  * Judgment & Tactics: Flawed, erratic, or panic-driven tactical judgment expends excess focus (negative).
  * Recovery & Clarity: Positive if the player took a moment to steady their breathing, meditate, regain composure, or gain tactical clarity.
- focus_delta_reason: A concise sentence explaining the mental/magical justification for focus_delta based on judgment, strain, or recovery. Set to null if focus_delta is 0.

2. World State Mutations:
- location: Set only if the narration explicitly moved the player to a distinctly new named area.
- mood: A single evocative word capturing the player's emotional state (e.g. 'Wary', 'Relieved', 'Grim', 'Determined').
- items_gained: List of concrete physical objects the player acquired or picked up (name and short description).
- items_lost: List of item names dropped, shattered, consumed, or traded away.
- npc_relationship_deltas: Record changes for any NPC interacted with, including an observation note from their viewpoint.
- quests_completed: List of active quest titles that were clearly fulfilled, resolved, or completed by events this turn.
- facts_established: Short, declarative world facts explicitly proven true this turn (e.g. 'the gate is barred with iron').
"""


async def extract_state_delta(
    action_text: str,
    narration_text: str,
    session: GameSession,
    parent_node: Optional[StoryNode] = None,
    llm_client: Optional[LLMClient] = None,
) -> StateDelta:
    """Force-extract schema-validated state changes from narration and action."""
    client = llm_client or get_llm_client()

    prompt_parts = [
        f"Player Action: {action_text}",
        f"Resulting Narration:\n{narration_text}",
        f"Current State: Location '{session.location}', HP {session.hp}/{session.max_hp}, Mood '{session.mood}'",
    ]
    if parent_node and parent_node.facts:
        prompt_parts.append(f"Previously Known Facts: {'; '.join(parent_node.facts)}")

    prompt_parts.append("Extract all state changes, newly established facts, and NPC interactions:")
    prompt = "\n\n".join(prompt_parts)

    return await client.generate_structured(
        prompt=prompt,
        response_model=StateDelta,
        system_prompt=STATE_EXTRACTOR_SYSTEM_PROMPT,
        temperature=0.1,
    )


ATTRITION_HP = -1
ATTRITION_FOCUS = -2


async def generate_game_over_summary(
    session: GameSession,
    action_text: str,
    narration_text: str,
    llm_client: Optional[LLMClient] = None,
) -> str:
    """Generate a one-paragraph narrative epitaph for a fallen adventurer."""
    client = llm_client or get_llm_client()
    from app.llm_client import MockLLMClient

    if isinstance(client, MockLLMClient):
        if session.game_over_reason == "death":
            return (
                f"The journey ends in blood and shadow at {session.location}. Mortally wounded from physical "
                f"perils, your lifeblood seeps into the dark earth, leaving your quest unfinished and your name lost to the mists."
            )
        else:
            return (
                f"Mind shattered and will broken, you collapse into delirium amidst the silence of {session.location}. "
                f"Exhausted beyond endurance, you surrender to the encroaching dark, unable to carry on."
            )

    prompt = (
        f"The player has suffered a game over ({session.game_over_reason.upper()}) in Aetherfall.\n"
        f"Location: {session.location}\n"
        f"Final Action: {action_text}\n"
        f"Final Narration: {narration_text}\n\n"
        f"Write a somber, atmospheric one-paragraph narrative epitaph (3-4 sentences) summarizing their tragic end."
    )
    try:
        chunks = []
        async for chunk in client.generate_stream(
            prompt=prompt,
            system_prompt="You are a somber dark fantasy chronicler composing an epitaph.",
            max_tokens=200,
            temperature=0.7,
        ):
            chunks.append(chunk)
        summary = "".join(chunks).strip()
        if summary:
            return summary
    except Exception:
        pass

    if session.game_over_reason == "death":
        return f"Mortally wounded at {session.location}, the adventurer perished before fulfilling their quest."
    return f"Overcome by mental and spiritual collapse at {session.location}, the wanderer succumbed to oblivion."


async def generate_victory_summary(
    session: GameSession,
    action_text: str,
    narration_text: str,
    llm_client: Optional[LLMClient] = None,
) -> str:
    """Generate an inspiring, triumphant one-paragraph narrative chronicle for saving the realm."""
    client = llm_client or get_llm_client()
    from app.llm_client import MockLLMClient

    if isinstance(client, MockLLMClient):
        return (
            f"Against all odds, the floodwaters recede from {session.location}. The ancient curse has broken, "
            f"and the Sunken Reach is saved. Songs of your triumph will echo through the halls for generations to come."
        )

    prompt = (
        f"The player has achieved VICTORY in Aetherfall by completing Chapter 4: The Reach's End!\n"
        f"Location: {session.location}\n"
        f"Final Action: {action_text}\n"
        f"Final Narration: {narration_text}\n\n"
        f"Write an inspiring, triumphant one-paragraph narrative chronicle (3-4 sentences) celebrating their victory, "
        f"the ending of the deluge, and their enduring heroic legacy across the realm."
    )
    try:
        chunks = []
        async for chunk in client.generate_stream(
            prompt=prompt,
            system_prompt="You are an inspiring chronicler of epic fantasy legends recording a momentous heroic victory.",
            max_tokens=200,
            temperature=0.7,
        ):
            chunks.append(chunk)
        summary = "".join(chunks).strip()
        if summary:
            return summary
    except Exception:
        pass

    return (
        f"Against all odds, the deluge receded and the source of the flood was vanquished at {session.location}. "
        f"The realm of Aetherfall stands saved."
    )


async def apply_state_delta(
    db_session: AsyncSession,
    session: GameSession,
    delta: StateDelta,
    parent_node: Optional[StoryNode],
    action_text: str,
    narration_text: str,
    llm_client: Optional[LLMClient] = None,
) -> StoryNode:
    """Create the new StoryNode and apply all delta updates to persistent database rows."""
    # 1. Determine turn number and create the new immutable StoryNode
    next_turn_number = (parent_node.turn_number + 1) if parent_node else 1
    new_location = delta.location or session.location

    new_node = StoryNode(
        session_id=session.id,
        parent_id=parent_node.id if parent_node else None,
        turn_number=next_turn_number,
        player_action=action_text,
        narration=narration_text,
        location=new_location,
        facts=delta.facts_established or [],
    )
    db_session.add(new_node)
    await db_session.flush()

    # 2. Update denormalized GameSession state fields
    # Apply extracted deltas + deterministic per-turn attrition (-1 HP, -2 Focus), clamped to [0, max]
    extracted_hp = delta.hp_delta if delta.hp_delta != 0 else delta.hp_change
    extracted_focus = delta.focus_delta if delta.focus_delta != 0 else delta.focus_change

    session.hp = max(0, min(session.max_hp, session.hp + extracted_hp + ATTRITION_HP))
    session.focus = max(0, min(session.max_focus, session.focus + extracted_focus + ATTRITION_FOCUS))

    # Live Game-Over evaluation (HP takes priority if both hit 0 in the same turn)
    if session.hp == 0:
        session.is_game_over = True
        session.game_over_reason = "death"
        session.game_over_summary = await generate_game_over_summary(
            session=session,
            action_text=action_text,
            narration_text=narration_text,
            llm_client=llm_client,
        )
    elif session.focus == 0:
        session.is_game_over = True
        session.game_over_reason = "collapse"
        session.game_over_summary = await generate_game_over_summary(
            session=session,
            action_text=action_text,
            narration_text=narration_text,
            llm_client=llm_client,
        )

    if delta.location:
        session.location = delta.location
    if delta.mood:
        session.mood = delta.mood

    session.turn_count = (session.turn_count or 0) + 1
    session.current_node_id = new_node.id

    # 3. Add gained inventory items
    for item_gain in delta.items_gained:
        inv_item = InventoryItem(
            session_id=session.id,
            name=item_gain.name,
            description=item_gain.description or "",
            acquired_at_node_id=new_node.id,
        )
        db_session.add(inv_item)

    # 4. Handle lost inventory items
    if delta.items_lost:
        # Load active inventory for session if not already in session identity map
        stmt = select(InventoryItem).where(InventoryItem.session_id == session.id)
        result = await db_session.execute(stmt)
        existing_items = result.scalars().all()

        lost_names = {name.strip().lower() for name in delta.items_lost}
        for item in existing_items:
            if item.name.strip().lower() in lost_names:
                await db_session.delete(item)

    # 5. Apply NPC affinity changes and record new NPC memory entries
    for npc_delta in delta.npc_relationship_deltas:
        clean_name = npc_delta.npc_name.strip()
        if not clean_name:
            continue

        # Lookup NPC in session
        stmt = (
            select(NPC)
            .where(NPC.session_id == session.id)
            .where(NPC.name.ilike(clean_name))
            .options(selectinload(NPC.memories))
        )
        result = await db_session.execute(stmt)
        npc = result.scalar_one_or_none()

        if not npc:
            # First encounter with this NPC: create character row
            npc = NPC(
                session_id=session.id,
                name=clean_name,
                description=f"An acquaintance encountered in {session.location}.",
                relationship_score=0,
            )
            db_session.add(npc)
            await db_session.flush()

        # Update affinity score clamped within [-100, 100]
        npc.relationship_score = max(-100, min(100, npc.relationship_score + npc_delta.delta))

        # Record memory entry from NPC's perspective
        if npc_delta.memory_note:
            salience = min(10, max(1, abs(npc_delta.delta) // 2 + 4))
            memory = NPCMemoryEntry(
                npc_id=npc.id,
                session_id=session.id,
                node_id=new_node.id,
                content=npc_delta.memory_note,
                salience=salience,
            )
            db_session.add(memory)

    # 6. Apply quest completions
    if delta.quests_completed:
        stmt = (
            select(Quest)
            .where(Quest.session_id == session.id)
            .where(Quest.status == "active")
        )
        result = await db_session.execute(stmt)
        active_quests = result.scalars().all()
        completed_titles = {t.strip().lower() for t in delta.quests_completed}
        for quest in active_quests:
            if quest.title.strip().lower() in completed_titles:
                quest.status = "completed"
                quest.updated_at_node_id = new_node.id

    return new_node
