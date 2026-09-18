"""Turn Pipeline Orchestrator for Aetherfall.

Orchestrates the four specialized agents for a single player turn:
1. NPC Memory Agent: Computes relevance scores against NPCs in scene -> extracts best memory.
2. Narrator Agent: Generates narrative prose incorporating scene context and recalled memory.
3. State-Extraction Agent: Extracts structured StateDelta and commits database updates.
4. Continuity Guard: Verifies narration against ancestor facts in the active story branch.

Branching Support:
The `from_node_id` parameter enables replaying from an earlier node. When provided,
the new StoryNode's parent_id is anchored to that ancestor node, cleanly forking
a new branch while preserving the original branch in the story tree.
"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.continuity_guard import check_continuity
from app.agents.narrator import generate_narration
from app.agents.npc_memory import find_scene_best_recall
from app.agents.state_extractor import apply_state_delta, extract_state_delta
from app.database import async_session_maker
from app.llm_client import LLMClient, get_llm_client
from app.models import GameSession, NPC, StoryNode
from app.schemas import RecalledMemory, TurnResult


async def run_turn(
    session_id: str,
    action_text: str,
    from_node_id: Optional[str] = None,
    db_session: Optional[AsyncSession] = None,
    llm_client: Optional[LLMClient] = None,
) -> TurnResult:
    """Execute a complete narrative turn across the four-agent pipeline."""
    if db_session is None:
        async with async_session_maker() as owned_session:
            result = await _execute_pipeline(
                db_session=owned_session,
                session_id=session_id,
                action_text=action_text,
                from_node_id=from_node_id,
                llm_client=llm_client,
            )
            await owned_session.commit()
            return result

    return await _execute_pipeline(
        db_session=db_session,
        session_id=session_id,
        action_text=action_text,
        from_node_id=from_node_id,
        llm_client=llm_client,
    )


async def _execute_pipeline(
    db_session: AsyncSession,
    session_id: str,
    action_text: str,
    from_node_id: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
) -> TurnResult:
    client = llm_client or get_llm_client()

    # 1. Load GameSession with eager NPC memories and inventory to prevent MissingGreenlet
    stmt = (
        select(GameSession)
        .where(GameSession.id == session_id)
        .options(
            selectinload(GameSession.npcs).selectinload(NPC.memories),
            selectinload(GameSession.inventory),
        )
    )
    result = await db_session.execute(stmt)
    game_session = result.scalar_one_or_none()
    if not game_session:
        raise ValueError(f"GameSession with id '{session_id}' not found.")

    # 2. Determine parent StoryNode (supports branching via from_node_id)
    target_parent_id = from_node_id if from_node_id is not None else game_session.current_node_id
    parent_node: Optional[StoryNode] = None
    if target_parent_id:
        parent_node = await db_session.get(StoryNode, target_parent_id)
        if not parent_node:
            raise ValueError(f"Target parent StoryNode '{target_parent_id}' not found.")

    current_turn = parent_node.turn_number if parent_node else 0

    # 3. Step 1: Run NPC Memory Agent (Pure-Python lexical & salience scoring)
    best_scene_recall = find_scene_best_recall(
        npcs=game_session.npcs,
        action_text=action_text,
        current_turn=current_turn,
        threshold=0.25,
    )
    recalled_schema: Optional[RecalledMemory] = None
    if best_scene_recall:
        npc, memory, score = best_scene_recall
        recalled_schema = RecalledMemory(
            npc_name=npc.name,
            npc_id=npc.id,
            memory_id=memory.id,
            content=memory.content,
            salience=memory.salience,
            score=score,
        )

    # 4. Step 2: Run Narrator Agent (Streaming generation collected to prose)
    narration_text = await generate_narration(
        action_text=action_text,
        session=game_session,
        parent_node=parent_node,
        recalled_memory=best_scene_recall,
        llm_client=client,
    )

    # 5. Step 3: Run State-Extraction Agent (Force schema -> commit DB mutations)
    state_delta = await extract_state_delta(
        action_text=action_text,
        narration_text=narration_text,
        session=game_session,
        parent_node=parent_node,
        llm_client=client,
    )
    new_node = await apply_state_delta(
        db_session=db_session,
        session=game_session,
        delta=state_delta,
        parent_node=parent_node,
        action_text=action_text,
        narration_text=narration_text,
    )

    # 6. Step 4: Run Continuity Guard (Tier-1 short-circuit -> Tier-2 LLM check)
    continuity_result = await check_continuity(
        db_session=db_session,
        new_node=new_node,
        narration_text=narration_text,
        llm_client=client,
    )

    await db_session.flush()

    return TurnResult(
        session_id=game_session.id,
        node_id=new_node.id,
        parent_id=new_node.parent_id,
        turn_number=new_node.turn_number,
        narration=new_node.narration,
        player_action=new_node.player_action,
        location=game_session.location,
        mood=game_session.mood,
        hp=game_session.hp,
        focus=game_session.focus,
        state_delta=state_delta,
        continuity=continuity_result,
        recalled_memory=recalled_schema,
    )
