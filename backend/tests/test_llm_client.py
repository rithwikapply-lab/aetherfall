import pytest
from pydantic import BaseModel

from app.llm_client import (
    AnthropicLLMClient,
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
