"""Continuity Guard Agent for Aetherfall.

==============================================================================
TWO-TIER CONTINUITY CHECK ARCHITECTURE
==============================================================================
The Continuity Guard verifies that newly generated narrative prose does not
contradict immutable world facts established earlier in the current story branch.

To minimize latency and avoid unnecessary LLM costs:
- Tier 1 (Pure Short-Circuit): If the ancestor branch contains zero established
  facts (common in opening turns), skip the LLM call entirely and return
  has_contradiction=False immediately.
  NOTE FOR TESTING: The test suite must explicitly prove this short-circuit by
  passing a fake LLM client that raises an exception if invoked; the call must
  succeed cleanly without touching the LLM when no facts exist.
- Tier 2 (Structured LLM Verification): Only executes when established facts exist
  in the ancestor tree. Enforces the `ContinuityResult` Pydantic schema via native
  forced tool use, producing structured, explainable contradiction reports.
==============================================================================
"""

from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_client import LLMClient, get_llm_client
from app.models import StoryNode
from app.schemas import ContinuityResult

CONTINUITY_GUARD_SYSTEM_PROMPT = """You are the Continuity Guard for Aetherfall.
Your job is to analyze the latest narrative prose against the list of canon facts established earlier in this story branch.
Determine if the new narration contains a direct contradiction with any established fact.

Rules:
- has_contradiction: True ONLY if the narration directly asserts something impossible according to an established fact (e.g. established: 'Kael is blind in his left eye'; narration: 'Kael winked with his left eye').
- If a contradiction exists, identify the exact contradicting_claim, the established_fact violated, and the reason.
- If the narration is coherent or simply introduces new consistent details, return has_contradiction=False.
"""


async def collect_ancestor_facts(
    db_session: AsyncSession,
    start_node_id: Optional[str],
) -> List[str]:
    """Walk up the story graph parent chain and collect all canon facts."""
    facts: List[str] = []
    current_id = start_node_id
    visited = set()

    while current_id and current_id not in visited:
        visited.add(current_id)
        node = await db_session.get(StoryNode, current_id)
        if not node:
            break
        if node.facts:
            facts.extend(node.facts)
        current_id = node.parent_id

    return facts


async def check_continuity(
    db_session: AsyncSession,
    new_node: StoryNode,
    narration_text: str,
    llm_client: Optional[LLMClient] = None,
) -> ContinuityResult:
    """Evaluate narration against ancestor branch facts using two-tier verification."""
    # Collect facts established earlier in this story branch (ancestors of new_node)
    ancestor_facts = await collect_ancestor_facts(db_session, new_node.parent_id)

    # --------------------------------------------------------------------------
    # TIER 1: Pure Short-Circuit
    # If no ancestor facts exist yet, bypass the LLM entirely.
    # --------------------------------------------------------------------------
    if not ancestor_facts:
        return ContinuityResult(
            has_contradiction=False,
            reason="Tier 1 short-circuit: No prior established facts in ancestor branch.",
        )

    # --------------------------------------------------------------------------
    # TIER 2: Structured LLM Verification
    # Facts exist — invoke structured output to verify narrative coherence.
    # --------------------------------------------------------------------------
    client = llm_client or get_llm_client()

    prompt = (
        f"Established Canon Facts for this Branch:\n- "
        + "\n- ".join(ancestor_facts)
        + f"\n\nNew Turn Narration to Verify:\n{narration_text}\n\n"
        + "Check if any established fact is directly contradicted:"
    )

    return await client.generate_structured(
        prompt=prompt,
        response_model=ContinuityResult,
        system_prompt=CONTINUITY_GUARD_SYSTEM_PROMPT,
        temperature=0.0,
    )
