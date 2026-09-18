import pytest
from pydantic import BaseModel

from app.llm_client import (
    AnthropicLLMClient,
    GeminiLLMClient,
    LLMClient,
    MockLLMClient,
    get_llm_client,
)


class SampleWorldStateDelta(BaseModel):
    hp_change: int
    mood: str
    discovered_facts: list[str]
    continuity_valid: bool


@pytest.mark.asyncio
async def test_get_llm_client_defaults_to_mock():
    # Without ANTHROPIC_API_KEY configured, factory must return MockLLMClient
    client = get_llm_client()
    assert isinstance(client, MockLLMClient)
    assert isinstance(client, LLMClient)


@pytest.mark.asyncio
async def test_mock_client_streaming():
    client = get_llm_client(force_mock=True)

    chunks: list[str] = []
    async for chunk in client.generate_stream(
        prompt="Approach the ruined sanctuary.",
        system_prompt="You are a grim fantasy narrator.",
    ):
        chunks.append(chunk)

    full_narrative = "".join(chunks)
    assert len(chunks) > 0
    assert len(full_narrative.strip()) > 0
    assert isinstance(full_narrative, str)


@pytest.mark.asyncio
async def test_mock_client_structured_output():
    client = get_llm_client(force_mock=True)

    result = await client.generate_structured(
        prompt="Analyze turn outcome: player drank from murky spring.",
        response_model=SampleWorldStateDelta,
        system_prompt="Extract game state updates.",
    )

    # Must return an instantiated and validated Pydantic model, not a dict or raw string
    assert isinstance(result, SampleWorldStateDelta)
    assert isinstance(result.hp_change, int)
    assert isinstance(result.mood, str)
    assert len(result.mood) > 0
    assert isinstance(result.discovered_facts, list)
    assert len(result.discovered_facts) > 0
    assert isinstance(result.continuity_valid, bool)


def test_anthropic_client_interface():
    # Confirm AnthropicLLMClient conforms to abstract interface without spending credits
    assert issubclass(AnthropicLLMClient, LLMClient)

    # Error handling when no API key provided
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
        AnthropicLLMClient(api_key="")

    # Instantiation with dummy key succeeds
    dummy_client = AnthropicLLMClient(api_key="sk-ant-dummy-test-key", model="claude-sonnet-4-5")
    assert dummy_client.model == "claude-sonnet-4-5"
    assert hasattr(dummy_client, "generate_stream")
    assert hasattr(dummy_client, "generate_structured")


def test_gemini_client_interface():
    # Confirm GeminiLLMClient conforms to abstract interface without spending credits
    assert issubclass(GeminiLLMClient, LLMClient)

    # Error handling when no API key provided
    with pytest.raises(ValueError, match="GOOGLE_API_KEY is required"):
        GeminiLLMClient(api_key="")

    # Instantiation with dummy key succeeds
    dummy_client = GeminiLLMClient(api_key="dummy-gemini-test-key", model="gemini-2.5-flash")
    assert dummy_client.model == "gemini-2.5-flash"
    assert hasattr(dummy_client, "generate_stream")
    assert hasattr(dummy_client, "generate_structured")


def test_get_llm_client_provider_precedence(monkeypatch):
    from app.config import settings

    # Case 1: Neither key configured -> MockLLMClient
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    client = get_llm_client()
    assert isinstance(client, MockLLMClient)

    # Case 2: Only GOOGLE_API_KEY configured -> GeminiLLMClient
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "dummy-gemini-key")
    client = get_llm_client()
    assert isinstance(client, GeminiLLMClient)
    assert isinstance(client, LLMClient)

    # Case 3: Both configured -> Anthropic takes precedence
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "dummy-anthropic-key")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "dummy-gemini-key")
    client = get_llm_client()
    assert isinstance(client, AnthropicLLMClient)

    # Case 4: force_mock=True always returns MockLLMClient
    client_forced = get_llm_client(force_mock=True)
    assert isinstance(client_forced, MockLLMClient)


@pytest.mark.asyncio
async def test_gemini_client_streaming_mocked():
    from unittest.mock import MagicMock

    gemini = GeminiLLMClient(api_key="dummy-gemini-key")

    async def fake_stream(*args, **kwargs):
        chunk1 = MagicMock()
        chunk1.text = "The ancient archway looms."
        chunk2 = MagicMock()
        chunk2.text = " Mist gathers at your feet."
        yield chunk1
        yield chunk2

    gemini._client.aio.models.generate_content_stream = fake_stream

    chunks = []
    async for chunk in gemini.generate_stream("Describe the entrance."):
        chunks.append(chunk)

    assert "".join(chunks) == "The ancient archway looms. Mist gathers at your feet."


@pytest.mark.asyncio
async def test_gemini_client_structured_output_mocked():
    from unittest.mock import AsyncMock, MagicMock

    gemini = GeminiLLMClient(api_key="dummy-gemini-key")

    mock_resp = MagicMock()
    mock_resp.parsed = SampleWorldStateDelta(
        hp_change=-5,
        mood="Wary",
        discovered_facts=["The crypt is damp."],
        continuity_valid=True,
    )
    mock_resp.text = None

    gemini._client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    res = await gemini.generate_structured(
        prompt="Analyze turn outcome.",
        response_model=SampleWorldStateDelta,
    )
    assert isinstance(res, SampleWorldStateDelta)
    assert res.hp_change == -5
    assert res.mood == "Wary"
    assert res.continuity_valid is True


@pytest.mark.asyncio
async def test_mock_statedelta_combat_keyword():
    from app.schemas import StateDelta

    client = get_llm_client(force_mock=True)

    # Prompt with "attack"
    res_attack = await client.generate_structured(
        prompt="The player attacks the drowned lurker with their blade.",
        response_model=StateDelta,
    )
    assert isinstance(res_attack, StateDelta)
    assert res_attack.hp_change < 0
    assert -15 <= res_attack.hp_change <= -1
    assert len(res_attack.items_gained) == 0
    assert len(res_attack.npc_relationship_deltas) == 0

    # Determinism: same prompt yields identical damage value
    res_attack_repeat = await client.generate_structured(
        prompt="The player attacks the drowned lurker with their blade.",
        response_model=StateDelta,
    )
    assert res_attack.hp_change == res_attack_repeat.hp_change

    # Other combat keywords: "fight", "strike", "hit"
    for kw in ("fight", "strike", "hit"):
        res = await client.generate_structured(
            prompt=f"Prepare to {kw} the shadowy monstrosity.",
            response_model=StateDelta,
        )
        assert res.hp_change < 0
        assert -15 <= res.hp_change <= -1


@pytest.mark.asyncio
async def test_mock_statedelta_search_keyword():
    from app.schemas import StateDelta

    client = get_llm_client(force_mock=True)

    # Prompt with "search"
    res_search = await client.generate_structured(
        prompt="Search the decaying chest buried beneath the silt.",
        response_model=StateDelta,
    )
    assert isinstance(res_search, StateDelta)
    assert len(res_search.items_gained) >= 1
    assert len(res_search.items_gained[0].name) > 0
    assert len(res_search.items_gained[0].description) > 0
    assert res_search.hp_change == 0
    assert len(res_search.npc_relationship_deltas) == 0

    # Other search keywords: "look", "examine", "take"
    for kw in ("look", "examine", "take"):
        res = await client.generate_structured(
            prompt=f"Carefully {kw} the rubble on the stone altar.",
            response_model=StateDelta,
        )
        assert len(res.items_gained) >= 1
        assert res.hp_change == 0


@pytest.mark.asyncio
async def test_mock_statedelta_dialogue_keyword():
    from app.schemas import StateDelta

    client = get_llm_client(force_mock=True)

    # Prompt with "ask" mentioning Kael
    res_ask = await client.generate_structured(
        prompt="Ask Kael about the history of the sunken bridge.",
        response_model=StateDelta,
    )
    assert isinstance(res_ask, StateDelta)
    assert len(res_ask.npc_relationship_deltas) >= 1
    npc_delta = res_ask.npc_relationship_deltas[0]
    assert npc_delta.npc_name == "Kael"
    assert npc_delta.delta > 0
    assert len(npc_delta.memory_note) > 0
    assert res_ask.hp_change == 0
    assert len(res_ask.items_gained) == 0

    # Other dialogue keywords: "talk", "tell", "speak"
    for kw in ("talk", "tell", "speak"):
        res = await client.generate_structured(
            prompt=f"Attempt to {kw} to the hooded traveler by the gate.",
            response_model=StateDelta,
        )
        assert len(res.npc_relationship_deltas) >= 1
        assert res.hp_change == 0
        assert len(res.items_gained) == 0


@pytest.mark.asyncio
async def test_mock_statedelta_neutral_fallback():
    from app.schemas import StateDelta

    client = get_llm_client(force_mock=True)

    # Neutral prompt without combat, search, or dialogue keywords
    res_neutral = await client.generate_structured(
        prompt="Meditate quietly beside the smoldering hearth embers.",
        response_model=StateDelta,
    )
    assert isinstance(res_neutral, StateDelta)
    # Generic generator produced valid instance without errors
    assert hasattr(res_neutral, "hp_change")
    assert hasattr(res_neutral, "items_gained")
    assert hasattr(res_neutral, "npc_relationship_deltas")

