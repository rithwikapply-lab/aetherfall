from types import SimpleNamespace
import pytest

from app.agents.npc_memory import (
    best_recall,
    find_scene_best_recall,
    retrieve_relevant,
    score_memory,
)
from app.models import NPC, NPCMemoryEntry, StoryNode


def test_relevance_ranking_favors_lexical_overlap():
    """Verify that memories with higher token overlap receive higher scores and rank first."""
    mem_bridge = NPCMemoryEntry(
        id="mem-bridge",
        content="The traveler offered fresh rations and asked about crossing the river bridge.",
        salience=8,
    )
    mem_tower = NPCMemoryEntry(
        id="mem-tower",
        content="Observed a flock of ravens roosting in the dilapidated bell tower at sunset.",
        salience=4,
    )
    npc = NPC(
        id="npc-kael",
        name="Kael",
        description="A cautious scout.",
        memories=[mem_bridge, mem_tower],
    )

    action = "Cross the flooded river bridge and share bread rations with the scout."
    ranked = retrieve_relevant(npc, action, current_turn=1, top_k=2)

    assert len(ranked) >= 1
    best_mem, best_score = ranked[0]
    assert best_mem.id == "mem-bridge"
    assert best_score > 0.35

    # If the tower memory is scored, it must score lower than bridge
    if len(ranked) > 1:
        assert ranked[0][1] > ranked[1][1]


def test_zero_lexical_overlap_returns_zero_score():
    """Verify that a memory with zero lexical overlap receives exactly 0.0,
    preventing spurious recall alerts.
    """
    mem = NPCMemoryEntry(
        id="mem-wolves",
        content="A pack of wolves howled across the distant frozen ridgeline at midnight.",
        salience=10,  # High salience must NOT override lack of lexical overlap
    )
    action = "Inspect the rusted iron padlock on the dungeon trapdoor."
    score = score_memory(mem, action, current_turn=5)

    assert score == 0.0


def test_recency_decay_lowers_score_for_older_memories():
    """Verify that recency decay produces a lower score for older memories
    when content, lexical overlap, and salience are otherwise identical.
    """
    node_recent = StoryNode(turn_number=10)
    node_old = StoryNode(turn_number=1)

    mem_recent = NPCMemoryEntry(
        id="mem-recent",
        content="Shared roasted root vegetables around the campfire during the thunderstorm.",
        salience=6,
    )
    mem_recent.node = node_recent

    mem_old = NPCMemoryEntry(
        id="mem-old",
        content="Shared roasted root vegetables around the campfire during the thunderstorm.",
        salience=6,
    )
    mem_old.node = node_old

    action = "Sit by the warm campfire and eat roasted vegetables."
    score_recent = score_memory(mem_recent, action, current_turn=10)
    score_old = score_memory(mem_old, action, current_turn=10)

    # Both must be non-zero and valid
    assert score_recent > 0.0
    assert score_old > 0.0

    # Recent memory (turn delta = 0) must score strictly higher than older memory (turn delta = 9)
    assert score_recent > score_old
    # delta is ~ 0.15 * (1.0 - 1.0/(1 + 0.9)) ~= 0.15 * (1 - 0.526) = ~0.071
    assert round(score_recent - score_old, 2) >= 0.05


def test_best_recall_returns_none_when_below_threshold():
    """Verify that best_recall returns None if no memory achieves the required threshold."""
    mem_slight = NPCMemoryEntry(
        id="mem-slight",
        content="The traveler carried a dull iron hunting knife in their leather belt.",
        salience=2,
    )
    npc = NPC(
        id="npc-kael",
        name="Kael",
        memories=[mem_slight],
    )

    # Action has only 1 overlapping stop-filtered word ("iron") in a long sentence
    action = "Examine the massive iron portcullis blocking the main castle gatehouse."
    # With a high threshold (e.g. 0.40), this faint overlap should not clear
    result = best_recall(npc, action, current_turn=1, threshold=0.40)
    assert result is None


def test_best_recall_returns_match_when_above_threshold():
    """Verify that best_recall successfully returns the top memory when threshold is met."""
    mem_strong = NPCMemoryEntry(
        id="mem-strong",
        content="The traveler warned Kael that the river bridge was broken and infested with leeches.",
        salience=9,
    )
    npc = NPC(
        id="npc-kael",
        name="Kael",
        memories=[mem_strong],
    )

    action = "Ask Kael about crossing the broken river bridge and the leeches."
    result = best_recall(npc, action, current_turn=1, threshold=0.25)

    assert result is not None
    recalled_mem, score = result
    assert recalled_mem.id == "mem-strong"
    assert score >= 0.25


def test_find_scene_best_recall_picks_highest_across_all_npcs():
    """Verify that find_scene_best_recall correctly compares memories across multiple NPCs
    and selects the globally highest scoring match.
    """
    mem_kael = NPCMemoryEntry(
        id="mem-kael",
        content="Kael noted that wolves hunt along the northern mountain ridge.",
        salience=5,
    )
    kael = NPC(id="npc-1", name="Kael", memories=[mem_kael])

    mem_elira = NPCMemoryEntry(
        id="mem-elira",
        content="Elira studied the ancient sun glyphs carved into the subterranean temple altar.",
        salience=9,
    )
    elira = NPC(id="npc-2", name="Elira", memories=[mem_elira])

    action = "Inspect the subterranean temple altar and decipher the sun glyphs."
    best = find_scene_best_recall([kael, elira], action, current_turn=2, threshold=0.25)

    assert best is not None
    matched_npc, matched_mem, score = best
    assert matched_npc.name == "Elira"
    assert matched_mem.id == "mem-elira"
    assert score > 0.4
