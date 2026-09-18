"""Aetherfall specialized narrative agents and turn pipeline."""

from app.agents.continuity_guard import check_continuity, collect_ancestor_facts
from app.agents.narrator import generate_narration, generate_narration_stream
from app.agents.npc_memory import best_recall, retrieve_relevant, score_memory
from app.agents.pipeline import run_turn
from app.agents.state_extractor import apply_state_delta, extract_state_delta

__all__ = [
    "run_turn",
    "generate_narration",
    "generate_narration_stream",
    "extract_state_delta",
    "apply_state_delta",
    "retrieve_relevant",
    "best_recall",
    "score_memory",
    "check_continuity",
    "collect_ancestor_facts",
]
