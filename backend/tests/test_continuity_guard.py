import pytest

from app.agents.continuity_guard import check_continuity, collect_ancestor_facts
from app.database import async_session_maker
from app.llm_client import LLMClient
from app.models import GameSession, StoryNode
from app.schemas import ContinuityResult


class ExplosiveLLMClient(LLMClient):
    """Raises an AssertionError if invoked, mathematically proving that Tier 1
    short-circuit bypasses all LLM invocations when no ancestor facts exist.
    """
    async def generate_stream(self, *args, **kwargs):
        raise AssertionError("ExplosiveLLMClient.generate_stream should NEVER be called in Tier 1!")

    async def generate_structured(self, *args, **kwargs):
        raise AssertionError("ExplosiveLLMClient.generate_structured should NEVER be called in Tier 1!")


class ContradictionMockLLMClient(LLMClient):
    """Mock LLM client that returns a structured continuity contradiction."""
    async def generate_stream(self, *args, **kwargs):
        yield "Contradiction detected."

    async def generate_structured(self, prompt, response_model, system_prompt=None, temperature=0.0):
        assert response_model is ContinuityResult
        return ContinuityResult(
            has_contradiction=True,
            contradicting_claim="You march confidently across the grand stone bridge",
            established_fact="the bridge was washed away in the great flood",
            reason="Narration describes walking across a bridge established as destroyed in the great flood.",
        )


class CoherentMockLLMClient(LLMClient):
    """Mock LLM client that returns a clean coherent continuity evaluation."""
    async def generate_stream(self, *args, **kwargs):
        yield "No contradiction."

    async def generate_structured(self, prompt, response_model, system_prompt=None, temperature=0.0):
        assert response_model is ContinuityResult
        return ContinuityResult(
            has_contradiction=False,
            reason="The narration respects that the bridge is out by seeking an alternative crossing.",
        )


@pytest.mark.asyncio
async def test_continuity_guard_tier1_short_circuit():
    """Prove that Tier 1 skips the LLM call entirely when zero ancestor facts exist."""
    async with async_session_maker() as session:
        game_session = GameSession(title="Continuity Short-Circuit Test")
        session.add(game_session)
        await session.flush()

        # Root node with NO established facts
        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The gate creaks open in the dead of night.",
            facts=[],
        )
        session.add(root_node)
        await session.flush()

        # Child node whose parent chain contains 0 facts
        child_node = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            narration="You walk down the damp corridor with your torch held high.",
            facts=[],
        )
        session.add(child_node)
        await session.commit()

        # Tier 1 check: Must return has_contradiction=False without invoking ExplosiveLLMClient
        result = await check_continuity(
            db_session=session,
            new_node=child_node,
            narration_text="You walk down the damp corridor with your torch held high.",
            llm_client=ExplosiveLLMClient(),
        )

        assert isinstance(result, ContinuityResult)
        assert result.has_contradiction is False
        assert result.contradicting_claim is None
        assert result.established_fact is None
        assert "Tier 1 short-circuit" in result.reason


@pytest.mark.asyncio
async def test_continuity_guard_tier2_detects_structured_contradiction():
    """Prove that Tier 2 invokes structured output and surfaces a contradiction."""
    async with async_session_maker() as session:
        game_session = GameSession(title="Continuity Contradiction Test")
        session.add(game_session)
        await session.flush()

        # Root node WITH established canon facts
        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The floodwaters churned through the canyon, ripping the bridge from its moorings.",
            facts=["the bridge was washed away in the great flood", "Kael lost his left eye in battle"],
        )
        session.add(root_node)
        await session.flush()

        # Child node that attempts to cross the destroyed bridge
        child_node = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            narration="You march confidently across the grand stone bridge into the lower courtyard.",
            facts=[],
        )
        session.add(child_node)
        await session.commit()

        result = await check_continuity(
            db_session=session,
            new_node=child_node,
            narration_text="You march confidently across the grand stone bridge into the lower courtyard.",
            llm_client=ContradictionMockLLMClient(),
        )

        assert isinstance(result, ContinuityResult)
        assert result.has_contradiction is True
        assert result.contradicting_claim == "You march confidently across the grand stone bridge"
        assert result.established_fact == "the bridge was washed away in the great flood"
        assert result.reason is not None
        assert "destroyed in the great flood" in result.reason


@pytest.mark.asyncio
async def test_continuity_guard_tier2_coherent_narration_passes():
    """Prove that Tier 2 returns has_contradiction=False when narration respects canon facts."""
    async with async_session_maker() as session:
        game_session = GameSession(title="Continuity Coherent Test")
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="The river roars below, empty of any crossing.",
            facts=["the bridge was washed away in the great flood"],
        )
        session.add(root_node)
        await session.flush()

        child_node = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            narration="You scout along the muddy riverbanks looking for a fallen tree to cross.",
            facts=["found a fallen pine tree"],
        )
        session.add(child_node)
        await session.commit()

        result = await check_continuity(
            db_session=session,
            new_node=child_node,
            narration_text="You scout along the muddy riverbanks looking for a fallen tree to cross.",
            llm_client=CoherentMockLLMClient(),
        )

        assert isinstance(result, ContinuityResult)
        assert result.has_contradiction is False
        assert result.contradicting_claim is None
        assert result.established_fact is None
        assert "alternative crossing" in result.reason


@pytest.mark.asyncio
async def test_collect_ancestor_facts_hierarchy():
    """Verify collect_ancestor_facts traverses multi-hop ancestor chains correctly."""
    async with async_session_maker() as session:
        game_session = GameSession(title="Ancestor Facts Chain Test")
        session.add(game_session)
        await session.flush()

        # Turn 0: Root
        node0 = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Turn 0",
            facts=["fact 0A", "fact 0B"],
        )
        session.add(node0)
        await session.flush()

        # Turn 1: Child of node0
        node1 = StoryNode(
            session_id=game_session.id,
            parent_id=node0.id,
            turn_number=1,
            narration="Turn 1",
            facts=["fact 1A"],
        )
        session.add(node1)
        await session.flush()

        # Turn 2: Child of node1
        node2 = StoryNode(
            session_id=game_session.id,
            parent_id=node1.id,
            turn_number=2,
            narration="Turn 2",
            facts=["fact 2A"],
        )
        session.add(node2)
        await session.commit()

        # Walking up from node2 (collects node2 facts, then node1, then node0)
        facts = await collect_ancestor_facts(session, node2.id)
        assert len(facts) == 4
        assert "fact 2A" in facts
        assert "fact 1A" in facts
        assert "fact 0A" in facts
        assert "fact 0B" in facts

        # Walking from node1
        facts_node1 = await collect_ancestor_facts(session, node1.id)
        assert len(facts_node1) == 3
        assert "fact 2A" not in facts_node1
        assert "fact 1A" in facts_node1
        assert "fact 0A" in facts_node1

        # Walking from None returns empty list
        assert await collect_ancestor_facts(session, None) == []
