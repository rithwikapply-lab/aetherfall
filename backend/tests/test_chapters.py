"""Unit and integration tests for Chapter Progression System (Stage B).

Tests:
1. Designated quest completion advances chapter_number and seeds the next chapter's quest.
2. Completing Chapter 4's quest triggers victory instead of advancing to a nonexistent Chapter 5.
3. completed_chapters accumulates correctly across multiple chapter transitions.
4. Completing a quest that is NOT the current chapter's designated completion quest does NOT advance anything.
5. Narrator prompt injects the current chapter's objective.
6. API endpoint GET /api/chapters returns all four canonical chapter definitions.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chapters import CHAPTERS, get_chapter, process_chapter_advancement
from app.agents.narrator import build_narrator_prompt
from app.agents.pipeline import run_turn
from app.agents.state_extractor import apply_state_delta
from app.database import async_session_maker
from app.llm_client import MockLLMClient
from app.main import app
from app.models import GameSession, Quest, StoryNode
from app.schemas import StateDelta


@pytest.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_api_get_chapters(api_client: AsyncClient):
    """Verify GET /api/chapters returns all four canonical chapter definitions."""
    res = await api_client.get("/api/chapters")
    assert res.status_code == 200
    chapters = res.json()
    assert len(chapters) == 4

    assert chapters[0]["number"] == 1
    assert chapters[0]["title"] == "The Drowned Road"
    assert chapters[0]["completion_quest_title"] == "Cross the Drowned Valley"
    assert chapters[0]["next_chapter_number"] == 2

    assert chapters[1]["number"] == 2
    assert chapters[1]["title"] == "The Ghost-Catcher's Ledger"
    assert chapters[1]["completion_quest_title"] == "Find Kael"
    assert chapters[1]["next_chapter_number"] == 3

    assert chapters[2]["number"] == 3
    assert chapters[2]["title"] == "The Salt-Bound Wraiths"
    assert chapters[2]["completion_quest_title"] == "Confront the Wraiths"
    assert chapters[2]["next_chapter_number"] == 4

    assert chapters[3]["number"] == 4
    assert chapters[3]["title"] == "The Reach's End"
    assert chapters[3]["completion_quest_title"] == "Reach the Source"
    assert chapters[3]["next_chapter_number"] is None


@pytest.mark.asyncio
async def test_narrator_prompt_injects_chapter_objective():
    """Verify narrator prompt incorporates the current chapter's objective."""
    session = GameSession(
        title="Test Chronicles",
        chapter_number=1,
        hp=100,
        max_hp=100,
        focus=50,
        max_focus=50,
        location="The Crossroads",
        mood="Wary",
    )
    prompt_ch1 = build_narrator_prompt("Look around", session)
    assert "Current Chapter Objective: Cross the flooded highway and find safe passage" in prompt_ch1

    session.chapter_number = 2
    prompt_ch2 = build_narrator_prompt("Look around", session)
    assert "Current Chapter Objective: Find Kael and learn what he knows about the wraiths in the flood" in prompt_ch2


@pytest.mark.asyncio
async def test_quest_completion_advances_chapter_and_seeds_next_quest():
    """Verify completing Chapter 1's quest advances to Chapter 2 and seeds Chapter 2's quest."""
    async with async_session_maker() as db:
        # 1. Setup session in Chapter 1 with active quest
        session = GameSession(
            title="Progression Test",
            chapter_number=1,
            completed_chapters=[],
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Crossroads",
        )
        db.add(session)
        await db.flush()

        root_node = StoryNode(
            session_id=session.id,
            parent_id=None,
            turn_number=0,
            narration="At the flooded crossroads.",
            location=session.location,
        )
        db.add(root_node)
        await db.flush()
        session.current_node_id = root_node.id

        quest_ch1 = Quest(
            session_id=session.id,
            title="Cross the Drowned Valley",
            status="active",
            description="Find safe passage across.",
            updated_at_node_id=root_node.id,
        )
        db.add(quest_ch1)
        await db.commit()
        session_id = session.id

    # 2. Run turn completing the designated quest
    turn_res = await run_turn(
        session_id=session_id,
        action_text="fulfill quest: Cross the Drowned Valley",
        llm_client=MockLLMClient(),
    )

    assert turn_res.chapter_advanced is True
    assert turn_res.chapter_number == 2
    assert turn_res.chapter == "Chapter 2: The Ghost-Catcher's Ledger"
    assert turn_res.completed_chapters == [1]

    # 3. Verify DB state: Chapter 2 active, Chapter 2 quest "Find Kael" seeded
    async with async_session_maker() as db:
        stmt = select(GameSession).where(GameSession.id == session_id)
        result = await db.execute(stmt)
        updated_session = result.scalar_one()

        assert updated_session.chapter_number == 2
        assert updated_session.chapter == "Chapter 2: The Ghost-Catcher's Ledger"
        assert updated_session.completed_chapters == [1]

        # Verify quests on session
        stmt_q = select(Quest).where(Quest.session_id == session_id)
        res_q = await db.execute(stmt_q)
        all_quests = res_q.scalars().all()

        q1 = next((q for q in all_quests if q.title == "Cross the Drowned Valley"), None)
        assert q1 is not None
        assert q1.status == "completed"

        q2 = next((q for q in all_quests if q.title == "Find Kael"), None)
        assert q2 is not None
        assert q2.status == "active"


@pytest.mark.asyncio
async def test_non_completion_quest_does_not_advance_chapter():
    """Verify completing an unrelated quest does NOT advance chapter progression."""
    async with async_session_maker() as db:
        session = GameSession(
            title="Side Quest Test",
            chapter_number=1,
            completed_chapters=[],
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Crossroads",
        )
        db.add(session)
        await db.flush()

        root_node = StoryNode(
            session_id=session.id,
            turn_number=0,
            narration="Crossroads.",
            location=session.location,
        )
        db.add(root_node)
        await db.flush()
        session.current_node_id = root_node.id

        main_q = Quest(
            session_id=session.id,
            title="Cross the Drowned Valley",
            status="active",
            description="Main objective.",
        )
        side_q = Quest(
            session_id=session.id,
            title="Inspect Ancient Waystone",
            status="active",
            description="A minor side mystery.",
        )
        db.add(main_q)
        db.add(side_q)
        await db.commit()
        session_id = session.id

    # Complete only the side quest
    turn_res = await run_turn(
        session_id=session_id,
        action_text="fulfill quest: Inspect Ancient Waystone",
        llm_client=MockLLMClient(),
    )

    # Chapter must NOT advance
    assert turn_res.chapter_advanced is False
    assert turn_res.chapter_number == 1
    assert turn_res.chapter == "Chapter 1: The Drowned Road"
    assert turn_res.completed_chapters == []

    async with async_session_maker() as db:
        stmt = select(GameSession).where(GameSession.id == session_id)
        result = await db.execute(stmt)
        s = result.scalar_one()
        assert s.chapter_number == 1
        assert s.completed_chapters == []

        # Ensure Chapter 2 quest was NOT seeded
        stmt_q = select(Quest).where(Quest.session_id == session_id).where(Quest.title == "Find Kael")
        res_q = await db.execute(stmt_q)
        assert res_q.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_chapter_4_completion_triggers_victory():
    """Verify completing Chapter 4 triggers Campaign Victory and does not advance to Chapter 5."""
    async with async_session_maker() as db:
        session = GameSession(
            title="Final Chapter Test",
            chapter_number=4,
            completed_chapters=[1, 2, 3],
            hp=80,
            max_hp=100,
            focus=40,
            max_focus=50,
            location="The Sluice Gates of the Reach",
        )
        db.add(session)
        await db.flush()

        node = StoryNode(
            session_id=session.id,
            turn_number=10,
            narration="Standing before the churning source of the flood.",
            location=session.location,
        )
        db.add(node)
        await db.flush()
        session.current_node_id = node.id

        ch4_q = Quest(
            session_id=session.id,
            title="Reach the Source",
            status="active",
            description="End the flooding at its origin.",
        )
        db.add(ch4_q)
        await db.commit()
        session_id = session.id

    turn_res = await run_turn(
        session_id=session_id,
        action_text="fulfill quest: Reach the Source",
        llm_client=MockLLMClient(),
    )

    assert turn_res.chapter_advanced is True
    assert turn_res.chapter_number == 4  # Does not advance to 5!
    assert turn_res.is_game_over is True
    assert turn_res.game_over_reason == "victory"
    assert "triumph" in turn_res.game_over_summary.lower() or "saved" in turn_res.game_over_summary.lower()
    assert turn_res.completed_chapters == [1, 2, 3, 4]

    async with async_session_maker() as db:
        stmt = select(GameSession).where(GameSession.id == session_id)
        result = await db.execute(stmt)
        s = result.scalar_one()

        assert s.is_game_over is True
        assert s.game_over_reason == "victory"
        assert s.chapter_number == 4
        assert s.completed_chapters == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_completed_chapters_accumulates_across_transitions():
    """Verify completed_chapters accumulates [1, 2, 3, 4] sequentially across all 4 chapters."""
    async with async_session_maker() as db:
        session = GameSession(
            title="Full Campaign Arc",
            chapter_number=1,
            completed_chapters=[],
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Sunken Crossroads",
        )
        db.add(session)
        await db.flush()

        node = StoryNode(
            session_id=session.id,
            turn_number=0,
            narration="Opening road.",
            location=session.location,
        )
        db.add(node)
        await db.flush()
        session.current_node_id = node.id

        q1 = Quest(
            session_id=session.id,
            title="Cross the Drowned Valley",
            status="active",
        )
        db.add(q1)
        await db.commit()
        session_id = session.id

    # Chapter 1 -> Chapter 2
    r1 = await run_turn(session_id, "fulfill quest: Cross the Drowned Valley", llm_client=MockLLMClient())
    assert r1.chapter_number == 2
    assert r1.completed_chapters == [1]

    # Chapter 2 -> Chapter 3
    r2 = await run_turn(session_id, "fulfill quest: Find Kael", llm_client=MockLLMClient())
    assert r2.chapter_number == 3
    assert r2.completed_chapters == [1, 2]

    # Chapter 3 -> Chapter 4
    r3 = await run_turn(session_id, "fulfill quest: Confront the Wraiths", llm_client=MockLLMClient())
    assert r3.chapter_number == 4
    assert r3.completed_chapters == [1, 2, 3]

    # Chapter 4 -> Victory
    r4 = await run_turn(session_id, "fulfill quest: Reach the Source", llm_client=MockLLMClient())
    assert r4.chapter_number == 4
    assert r4.completed_chapters == [1, 2, 3, 4]
    assert r4.is_game_over is True
    assert r4.game_over_reason == "victory"
