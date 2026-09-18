"""FastAPI routes for Aetherfall game sessions and streaming turn actions.

==============================================================================
CRITICAL LIFETIME & SSE PARSING DESIGN NOTES
==============================================================================
1. Database Session Lifetime for SSE:
   In `POST /api/sessions/{id}/action`, a short-lived DB session is used exclusively
   for the initial pre-check (returning a clean 404 immediately if the session or
   target branch node does not exist).
   Inside the `EventSourceResponse` async generator, a separate long-lived DB session
   is created (`async with async_session_maker() as db:`). It remains open across
   the entire streaming narration, state extraction, and continuity check, and commits
   upon completion. Do NOT use a request-scoped `Depends(get_db)` session for the
   SSE generator, as FastAPI closes dependency-injected sessions once the endpoint
   returns the Response object.

2. SSE Data Whitespace Formatting (Frontend Parser Note):
   According to the W3C Server-Sent Events specification, parsers strip exactly ONE
   leading space character following the 'data:' prefix.
   On the frontend, when parsing incoming 'event: chunk' lines:
   - Strip only the first leading space (e.g. line.slice(6) if line starts with 'data: ').
   - NEVER use `.trim()` or `.trimStart()` on the chunk, as doing so will destroy
     intentional paragraph breaks, indentations, and leading spaces in narrative prose!
==============================================================================
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from app.agents.continuity_guard import check_continuity
from app.agents.narrator import generate_narration_stream
from app.agents.npc_memory import find_scene_best_recall
from app.agents.state_extractor import apply_state_delta, extract_state_delta
from app.database import async_session_maker
from app.llm_client import get_llm_client
from app.models import GameSession, InventoryItem, NPC, Quest, StoryNode
from app.schemas import (
    ActionRequest,
    InventoryItemResponse,
    NPCResponse,
    QuestResponse,
    RecalledMemory,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStateResponse,
    StoryGraphResponse,
    StoryNodeDetailResponse,
    StoryNodeSummaryResponse,
    TurnResult,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post(
    "",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new GameSession with seeded opening StoryNode",
)
async def create_session(request: Optional[SessionCreateRequest] = None):
    """Initialize a new game campaign with opening narration and default world state."""
    title = (request.title if request and request.title else "The Sunken Reach")
    chapter = (request.chapter if request and request.chapter else "Chapter 1: The Drowned Road")

    async with async_session_maker() as db:
        # 1. Create GameSession with denormalized starting state
        session = GameSession(
            id=str(uuid.uuid4()),
            title=title,
            chapter=chapter,
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Crossroads",
            mood="Wary",
        )
        db.add(session)
        await db.flush()

        # 2. Create Root opening StoryNode (parent_id=None, turn_number=0)
        opening_narration = (
            "Rain lashes the mud-slicked stones of the crossroads. Ahead, the river has broken its banks, "
            "turning the ancient imperial highway into a churning mire of brackish water and rotting reeds. "
            "To your left, an old waystone stands tilted in the silt; to your right, a ruined stone gatehouse "
            "looms against the gray sky, a solitary lantern flickering in its arched embrasure."
        )
        root_node = StoryNode(
            session_id=session.id,
            parent_id=None,
            turn_number=0,
            player_action=None,
            narration=opening_narration,
            location="The Sunken Crossroads",
            facts=["the bridge is out", "the river has flooded the imperial highway"],
        )
        db.add(root_node)
        await db.flush()

        # Anchor active leaf to opening turn
        session.current_node_id = root_node.id

        # 3. Seed starter NPC: Kael
        kael = NPC(
            session_id=session.id,
            name="Kael",
            description="A cynical scout sheltering from the deluge in the ruined gatehouse.",
            relationship_score=0,
        )
        db.add(kael)

        # 4. Seed initial main quest
        main_quest = Quest(
            session_id=session.id,
            title="Cross the Drowned Valley",
            status="active",
            description="Find a passage or guide across the flooded river now that the bridge is submerged.",
            updated_at_node_id=root_node.id,
        )
        db.add(main_quest)

        await db.commit()
        await db.refresh(session)

        return SessionCreateResponse.model_validate(session)


@router.get(
    "/{session_id}/state",
    response_model=SessionStateResponse,
    summary="Get session denormalized state, inventory, quests, and NPCs",
)
async def get_session_state(session_id: str):
    """Retrieve full denormalized state for fast frontend status bar and inventory rendering."""
    async with async_session_maker() as db:
        stmt = (
            select(GameSession)
            .where(GameSession.id == session_id)
            .options(
                selectinload(GameSession.inventory),
                selectinload(GameSession.quests),
                selectinload(GameSession.npcs),
            )
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

        return SessionStateResponse(
            id=session.id,
            title=session.title,
            chapter=session.chapter,
            hp=session.hp,
            max_hp=session.max_hp,
            focus=session.focus,
            max_focus=session.max_focus,
            location=session.location,
            mood=session.mood,
            current_node_id=session.current_node_id,
            inventory=[InventoryItemResponse.model_validate(item) for item in session.inventory],
            quests=[QuestResponse.model_validate(q) for q in session.quests],
            npcs=[NPCResponse.model_validate(npc) for npc in session.npcs],
        )


@router.get(
    "/{session_id}/graph",
    response_model=StoryGraphResponse,
    summary="Get the full branching story tree for a session",
)
async def get_story_graph(session_id: str):
    """Retrieve all StoryNodes in a session to render the interactive tree on the frontend."""
    async with async_session_maker() as db:
        session = await db.get(GameSession, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

        stmt = (
            select(StoryNode)
            .where(StoryNode.session_id == session_id)
            .order_by(StoryNode.turn_number.asc(), StoryNode.created_at.asc())
        )
        result = await db.execute(stmt)
        nodes = result.scalars().all()

        return StoryGraphResponse(
            session_id=session.id,
            current_node_id=session.current_node_id,
            nodes=[StoryNodeSummaryResponse.model_validate(n) for n in nodes],
        )


@router.get(
    "/{session_id}/nodes/{node_id}",
    response_model=StoryNodeDetailResponse,
    summary="Get full details for a single StoryNode",
)
async def get_story_node_detail(session_id: str, node_id: str):
    """Inspect full narration, player action, and established facts for a specific turn node."""
    async with async_session_maker() as db:
        stmt = (
            select(StoryNode)
            .where(StoryNode.id == node_id)
            .where(StoryNode.session_id == session_id)
        )
        result = await db.execute(stmt)
        node = result.scalar_one_or_none()

        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"StoryNode '{node_id}' not found in session '{session_id}'.",
            )

        return StoryNodeDetailResponse.model_validate(node)


@router.post(
    "/{session_id}/action",
    summary="Execute a turn and stream narration and final state via SSE",
)
async def execute_turn_action(session_id: str, request: ActionRequest):
    """Stream narrative turn progression via Server-Sent Events (SSE).

    Emits 'event: chunk' with prose deltas, followed by 'event: done' containing
    the full structured TurnResult JSON payload.
    """
    # --------------------------------------------------------------------------
    # Pre-check: Verify existence with a short-lived DB session before streaming
    # --------------------------------------------------------------------------
    async with async_session_maker() as pre_check_db:
        session = await pre_check_db.get(GameSession, session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session '{session_id}' not found.",
            )

        if request.from_node_id:
            target_node = await pre_check_db.get(StoryNode, request.from_node_id)
            if not target_node or target_node.session_id != session_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target replay node '{request.from_node_id}' not found in session.",
                )

    # --------------------------------------------------------------------------
    # Long-lived SSE Event Generator with its own dedicated async DB session
    # --------------------------------------------------------------------------
    async def sse_event_stream():
        llm_client = get_llm_client()

        async with async_session_maker() as db:
            # 1. Load active GameSession with eager NPC memories to avoid MissingGreenlet
            stmt = (
                select(GameSession)
                .where(GameSession.id == session_id)
                .options(
                    selectinload(GameSession.npcs).selectinload(NPC.memories),
                    selectinload(GameSession.inventory),
                )
            )
            result = await db.execute(stmt)
            active_session = result.scalar_one()

            # 2. Determine parent StoryNode (supports branching via from_node_id)
            target_parent_id = request.from_node_id if request.from_node_id is not None else active_session.current_node_id
            parent_node: Optional[StoryNode] = None
            if target_parent_id:
                parent_node = await db.get(StoryNode, target_parent_id)

            current_turn = parent_node.turn_number if parent_node else 0

            # 3. Step 1: NPC Memory Agent
            best_scene_recall = find_scene_best_recall(
                npcs=active_session.npcs,
                action_text=request.action_text,
                current_turn=current_turn,
                threshold=0.25,
            )
            recalled_schema: Optional[RecalledMemory] = None
            if best_scene_recall:
                npc, mem, score = best_scene_recall
                recalled_schema = RecalledMemory(
                    npc_name=npc.name,
                    npc_id=npc.id,
                    memory_id=mem.id,
                    content=mem.content,
                    salience=mem.salience,
                    score=score,
                )

            # 4. Step 2: Narrator Agent Streaming
            narration_chunks = []
            async for chunk in generate_narration_stream(
                action_text=request.action_text,
                session=active_session,
                parent_node=parent_node,
                recalled_memory=best_scene_recall,
                llm_client=llm_client,
            ):
                narration_chunks.append(chunk)
                yield ServerSentEvent(event="chunk", data=chunk)

            full_narration = "".join(narration_chunks).strip()

            # 5. Step 3: State-Extraction Agent & Database Commit
            state_delta = await extract_state_delta(
                action_text=request.action_text,
                narration_text=full_narration,
                session=active_session,
                parent_node=parent_node,
                llm_client=llm_client,
            )
            new_node = await apply_state_delta(
                db_session=db,
                session=active_session,
                delta=state_delta,
                parent_node=parent_node,
                action_text=request.action_text,
                narration_text=full_narration,
            )

            # 6. Step 4: Continuity Guard
            continuity_result = await check_continuity(
                db_session=db,
                new_node=new_node,
                narration_text=full_narration,
                llm_client=llm_client,
            )

            await db.commit()
            await db.refresh(active_session)

            # 7. Final 'done' event with complete TurnResult JSON payload
            turn_result = TurnResult(
                session_id=active_session.id,
                node_id=new_node.id,
                parent_id=new_node.parent_id,
                turn_number=new_node.turn_number,
                narration=new_node.narration,
                player_action=new_node.player_action,
                location=active_session.location,
                mood=active_session.mood,
                hp=active_session.hp,
                focus=active_session.focus,
                state_delta=state_delta,
                continuity=continuity_result,
                recalled_memory=recalled_schema,
            )

            yield ServerSentEvent(
                event="done",
                data=turn_result.model_dump_json(),
            )

    return EventSourceResponse(sse_event_stream())
