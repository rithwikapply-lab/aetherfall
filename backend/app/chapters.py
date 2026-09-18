"""Chapter Definitions and Progression Engine for Aetherfall.

Defines the four core narrative chapters of the campaign, their objectives,
and their completion quest dependencies. Contains the deterministic chapter
advancement logic executed by the turn pipeline after state extraction.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import GameSession, Quest, StoryNode
from app.llm_client import LLMClient


class ChapterDefinition(BaseModel):
    """Metadata and progression rules for a single narrative chapter."""
    number: int
    title: str
    objective: str
    completion_quest_title: str
    completion_quest_description: str
    next_chapter_number: Optional[int] = None


# Canonical Four Chapters of Aetherfall
CHAPTERS: Dict[int, ChapterDefinition] = {
    1: ChapterDefinition(
        number=1,
        title="The Drowned Road",
        objective="Cross the flooded highway and find safe passage",
        completion_quest_title="Cross the Drowned Valley",
        completion_quest_description="Find a passage or guide across the flooded river now that the bridge is submerged.",
        next_chapter_number=2,
    ),
    2: ChapterDefinition(
        number=2,
        title="The Ghost-Catcher's Ledger",
        objective="Find Kael and learn what he knows about the wraiths in the flood",
        completion_quest_title="Find Kael",
        completion_quest_description="Seek out Kael and uncover what he knows about the wraiths haunting the floodwaters.",
        next_chapter_number=3,
    ),
    3: ChapterDefinition(
        number=3,
        title="The Salt-Bound Wraiths",
        objective="Deal with the things bound in the flood, bargain, banish, or flee",
        completion_quest_title="Confront the Wraiths",
        completion_quest_description="Confront the ancient entities bound within the deluge—negotiate, banish, or escape their grasp.",
        next_chapter_number=4,
    ),
    4: ChapterDefinition(
        number=4,
        title="The Reach's End",
        objective="Reach the source of the flooding and end it",
        completion_quest_title="Reach the Source",
        completion_quest_description="Venture into the heart of the deluge and extinguish the curse at its origin.",
        next_chapter_number=None,
    ),
}


def get_chapter(number: int) -> Optional[ChapterDefinition]:
    """Retrieve chapter definition by chapter number."""
    return CHAPTERS.get(number)


def get_all_chapters() -> List[ChapterDefinition]:
    """Return all defined chapters in ascending order."""
    return [CHAPTERS[k] for k in sorted(CHAPTERS.keys())]


def get_chapter_display_title(number: int) -> str:
    """Format canonical display title (e.g. 'Chapter 1: The Drowned Road')."""
    chap = CHAPTERS.get(number)
    if chap:
        return f"Chapter {chap.number}: {chap.title}"
    return f"Chapter {number}"


async def process_chapter_advancement(
    db_session: AsyncSession,
    session: GameSession,
    new_node: StoryNode,
    action_text: str,
    narration_text: str,
    pre_turn_quest_statuses: Dict[str, str],
    llm_client: Optional[LLMClient] = None,
) -> bool:
    """Deterministic chapter advancement logic executed post-extraction.

    Evaluates whether the current chapter's designated completion quest transitioned
    from 'active' to 'completed' this turn:
    - If yes:
      * Appends current chapter to session.completed_chapters
      * If next_chapter_number is not null: advances chapter_number and seeds next quest
      * If next_chapter_number is null (Chapter 4): triggers victory game-over state
      * Returns True
    - If no (or player is already dead/collapsed): returns False.
    """
    # 1. If player suffered game-over from HP/Focus exhaustion on this turn, do not advance
    if session.is_game_over and session.game_over_reason in ("death", "collapse"):
        return False

    current_chapter = get_chapter(session.chapter_number)
    if not current_chapter:
        return False

    target_quest_title = current_chapter.completion_quest_title.strip().lower()

    # 2. Check if this chapter's designated completion quest was active before this turn
    was_active = pre_turn_quest_statuses.get(target_quest_title) == "active"

    # 3. Check if this quest is now completed on the session
    stmt = (
        select(Quest)
        .where(Quest.session_id == session.id)
        .where(Quest.title.ilike(current_chapter.completion_quest_title))
    )
    result = await db_session.execute(stmt)
    matching_quest = result.scalar_one_or_none()

    now_completed = matching_quest is not None and matching_quest.status == "completed"

    # Must have just transitioned to completed this turn
    if not (was_active and now_completed):
        return False

    # 4. Record current chapter as completed
    completed_list = list(session.completed_chapters or [])
    if session.chapter_number not in completed_list:
        completed_list.append(session.chapter_number)
    session.completed_chapters = completed_list

    # 5. Advance to next chapter OR trigger Campaign Victory
    if current_chapter.next_chapter_number is not None:
        next_num = current_chapter.next_chapter_number
        next_chap = CHAPTERS[next_num]
        session.chapter_number = next_num

        # Seed next chapter's designated completion quest
        new_quest = Quest(
            session_id=session.id,
            title=next_chap.completion_quest_title,
            status="active",
            description=next_chap.completion_quest_description,
            updated_at_node_id=new_node.id,
        )
        db_session.add(new_quest)
        return True
    else:
        # Chapter 4 completed: Trigger Victory State!
        from app.agents.state_extractor import generate_victory_summary

        session.is_game_over = True
        session.game_over_reason = "victory"
        session.game_over_summary = await generate_victory_summary(
            session=session,
            action_text=action_text,
            narration_text=narration_text,
            llm_client=llm_client,
        )
        return True
