"""NPC Memory Agent for Aetherfall.

==============================================================================
DESIGN RATIONALE: PURE-PYTHON EXPLAINABLE SCORING
==============================================================================
This module implements a pure-Python lexical and salience scorer for NPC
memories. This is an intentional architectural decision, not a shortcut:
1. Explainability: Recall decisions can be audited and explained deterministically
   by pointing directly to the literal word overlap between player actions and
   NPC memory content.
2. Zero External Dependencies: Runs completely offline without vector databases,
   embedding services, or network calls, enabling rapid unit testing and local
   development.
3. Clean Swap Boundary: The `retrieve_relevant` and `best_recall` interfaces are
   clean abstractions. If vector/embedding search is introduced in a future
   phase, only the internal scoring function changes — calling code remains
   completely untouched.
==============================================================================
"""

import re
from typing import List, Optional, Tuple

from app.models import NPC, NPCMemoryEntry

# English stop words to ignore during lexical overlap calculation
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
    "to", "was", "were", "will", "with", "i", "you", "my", "your"
}


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercased words excluding stop words."""
    words = re.findall(r"\b[a-z0-9]+\b", text.lower())
    return {w for w in words if w not in STOP_WORDS and len(w) > 1}


def score_memory(
    memory: NPCMemoryEntry,
    action_text: str,
    current_turn: int = 0,
) -> float:
    """Compute relevance score for an NPC memory against a player action.

    Score components:
    - Lexical overlap (Jaccard similarity of meaningful tokens): weight 0.60
    - Salience (1-10 scale normalized): weight 0.25
    - Recency (decay over turn delta): weight 0.15

    If there is zero lexical overlap, the score remains 0.0 so unrelated
    memories never trigger false UI recall alerts.
    """
    action_tokens = _tokenize(action_text)
    memory_tokens = _tokenize(memory.content)

    if not action_tokens or not memory_tokens:
        return 0.0

    intersection = action_tokens & memory_tokens
    union = action_tokens | memory_tokens
    jaccard = len(intersection) / len(union) if union else 0.0

    # Strict gate: zero word overlap produces zero score
    if jaccard == 0.0:
        return 0.0

    # Normalized salience: 1-10 -> 0.1 to 1.0
    salience_norm = max(1, min(10, getattr(memory, "salience", 5))) / 10.0

    # Recency decay: safely inspect memory.__dict__ to avoid triggering lazy load on detached instance
    node = memory.__dict__.get("node")
    node_turn = getattr(node, "turn_number", 0) if node else 0
    turns_ago = max(0, current_turn - node_turn)
    recency = 1.0 / (1.0 + 0.1 * turns_ago)

    total_score = (0.60 * jaccard) + (0.25 * salience_norm) + (0.15 * recency)
    return round(total_score, 4)


def retrieve_relevant(
    npc: NPC,
    action_text: str,
    current_turn: int = 0,
    top_k: int = 3,
) -> List[Tuple[NPCMemoryEntry, float]]:
    """Return the top-k highest scoring memories for an NPC, sorted descending."""
    memories = getattr(npc, "memories", [])
    if not memories:
        return []

    scored: List[Tuple[NPCMemoryEntry, float]] = []
    for mem in memories:
        s = score_memory(mem, action_text, current_turn=current_turn)
        if s > 0.0:
            scored.append((mem, s))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def best_recall(
    npc: NPC,
    action_text: str,
    current_turn: int = 0,
    threshold: float = 0.25,
) -> Optional[Tuple[NPCMemoryEntry, float]]:
    """Return the single best memory for an NPC only if score exceeds threshold."""
    ranked = retrieve_relevant(npc, action_text, current_turn=current_turn, top_k=1)
    if ranked and ranked[0][1] >= threshold:
        return ranked[0]
    return None


def find_scene_best_recall(
    npcs: List[NPC],
    action_text: str,
    current_turn: int = 0,
    threshold: float = 0.25,
) -> Optional[Tuple[NPC, NPCMemoryEntry, float]]:
    """Find the single most relevant memory across all NPCs currently in the scene."""
    best_match: Optional[Tuple[NPC, NPCMemoryEntry, float]] = None
    best_score = 0.0

    for npc in npcs:
        recall = best_recall(npc, action_text, current_turn=current_turn, threshold=threshold)
        if recall and recall[1] > best_score:
            best_match = (npc, recall[0], recall[1])
            best_score = recall[1]

    return best_match
