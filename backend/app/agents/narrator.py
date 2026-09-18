"""Narrator Agent for Aetherfall.

The Narrator Agent is the voice of the Dungeon Master. It synthesizes the
player's action, environmental context from the active StoryNode, and recalled
NPC memories into descriptive narrative prose.

This is the only agent in the pipeline whose primary output is unstructured
natural language text, delivered via streaming for real-time player consumption.
"""

from typing import AsyncGenerator, Optional, Tuple

from app.llm_client import LLMClient, get_llm_client
from app.models import GameSession, NPC, NPCMemoryEntry, StoryNode

NARRATOR_SYSTEM_PROMPT = """You are the Dungeon Master and Narrator for Aetherfall, a dark, atmospheric interactive fiction fantasy engine.
Your role:
- Describe the immediate sensory and narrative consequences of the player's chosen action.
- Maintain a tone that is grounded, suspenseful, and evocative.
- If an NPC memory is provided, naturally weave that NPC's attitude or past history into the scene without breaking immersion.
- Keep the response to 1-3 rich, punchy paragraphs. Do not speak for the player; describe what happens around them and what they perceive.
- Chapter Objective: Keep the current chapter's objective in mind so the story pulls organically toward it rather than wandering indefinitely. Create opportunities for the player to progress the objective without railroading them into a single correct action.
"""


def build_narrator_prompt(
    action_text: str,
    session: GameSession,
    parent_node: Optional[StoryNode] = None,
    recalled_memory: Optional[Tuple[NPC, NPCMemoryEntry, float]] = None,
) -> str:
    """Construct the contextual prompt for narrative prose generation."""
    from app.chapters import get_chapter

    chapter_def = get_chapter(session.chapter_number)
    chapter_obj = chapter_def.objective if chapter_def else None

    prompt_parts = [
        f"Campaign: {session.title} | {session.chapter}",
        f"Current Location: {session.location}",
        f"Player Status: HP {session.hp}/{session.max_hp}, Mood: {session.mood}",
    ]
    if chapter_obj:
        prompt_parts.append(f"Current Chapter Objective: {chapter_obj}")

    if parent_node:
        prompt_parts.append(
            f"Preceding Scene Context (Turn {parent_node.turn_number}):\n{parent_node.narration}"
        )
        if parent_node.facts:
            facts_str = "; ".join(parent_node.facts)
            prompt_parts.append(f"Established World Facts: {facts_str}")

    if recalled_memory:
        npc, memory, score = recalled_memory
        prompt_parts.append(
            f"[NPC Memory Recall: {npc.name} (Relevance {score:.2f})]: '{memory.content}'"
        )

    prompt_parts.append(f"\nPlayer Action: > {action_text}\n\nNarrate what occurs next:")
    return "\n\n".join(prompt_parts)


async def generate_narration_stream(
    action_text: str,
    session: GameSession,
    parent_node: Optional[StoryNode] = None,
    recalled_memory: Optional[Tuple[NPC, NPCMemoryEntry, float]] = None,
    llm_client: Optional[LLMClient] = None,
) -> AsyncGenerator[str, None]:
    """Stream narrative text deltas for the player's action."""
    client = llm_client or get_llm_client()
    prompt = build_narrator_prompt(
        action_text=action_text,
        session=session,
        parent_node=parent_node,
        recalled_memory=recalled_memory,
    )

    async for chunk in client.generate_stream(
        prompt=prompt,
        system_prompt=NARRATOR_SYSTEM_PROMPT,
        max_tokens=600,
        temperature=0.7,
    ):
        yield chunk


async def generate_narration(
    action_text: str,
    session: GameSession,
    parent_node: Optional[StoryNode] = None,
    recalled_memory: Optional[Tuple[NPC, NPCMemoryEntry, float]] = None,
    llm_client: Optional[LLMClient] = None,
) -> str:
    """Convenience function that collects the full streamed narration into a string."""
    chunks = []
    async for chunk in generate_narration_stream(
        action_text=action_text,
        session=session,
        parent_node=parent_node,
        recalled_memory=recalled_memory,
        llm_client=llm_client,
    ):
        chunks.append(chunk)
    return "".join(chunks).strip()
