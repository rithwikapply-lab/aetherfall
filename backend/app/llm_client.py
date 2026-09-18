"""LLM Client Abstraction Layer for Aetherfall.

This module isolates all Large Language Model interactions behind an abstract
interface (`LLMClient`). The narrative agents (Narrator, State Extractor,
Continuity Guard, NPC Memory) only ever interact with `LLMClient`.

Key architectural principles:
1. Forced Structured Output: Rather than prompting models to "return JSON" and
   relying on fragile regex/json.loads parsing, `generate_structured` uses the
   provider's native forced tool-use mechanism (`tool_choice`). Responses are
   validated against Pydantic schemas before agent code ever sees them.
2. Zero Required External Dependencies: When no ANTHROPIC_API_KEY is configured,
   `get_llm_client()` automatically supplies `MockLLMClient`, providing fast,
   deterministic fantasy prose and schema-compliant outputs for testing and
   offline development.
3. Provider Encapsulation: `AnthropicLLMClient` is the single module in the entire
   codebase that imports or references the Anthropic SDK.
"""

import abc
import asyncio
import hashlib
import types
from typing import (
    AsyncGenerator,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)
from enum import Enum

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMClient(abc.ABC):
    """Abstract interface for LLM operations used by Aetherfall narrative agents."""

    @abc.abstractmethod
    def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Stream free-text generation as an async generator yielding string chunks.

        Used primarily by the Narrator agent for real-time Server-Sent Events (SSE).
        """
        pass

    @abc.abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.2,
    ) -> T:
        """Generate structured output validated against a Pydantic model class.

        Uses native forced tool-calling / structured output so the returned
        object is guaranteed to be an instantiated, validated `response_model`.
        """
        pass


class AnthropicLLMClient(LLMClient):
    """Production LLM client utilizing Anthropic's Messages API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required to initialize AnthropicLLMClient. "
                "Use MockLLMClient for offline development or testing."
            )
        self.model = model or settings.LLM_MODEL or "claude-sonnet-4-5"
        self._client = AsyncAnthropic(api_key=self.api_key)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Stream narrative text deltas from Claude using the Messages API."""
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.2,
    ) -> T:
        """Force Claude to invoke a single synthetic tool matching response_model's schema."""
        tool_name = response_model.__name__
        tool_schema = response_model.model_json_schema()

        tools = [
            {
                "name": tool_name,
                "description": f"Extract structured output for {tool_name}.",
                "input_schema": tool_schema,
            }
        ]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "tools": tools,
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._client.messages.create(**kwargs)

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return response_model.model_validate(block.input)

        raise ValueError(
            f"Anthropic model did not call requested tool '{tool_name}'. "
            f"Blocks returned: {response.content}"
        )


class MockLLMClient(LLMClient):
    """Deterministic, zero-dependency LLM client for offline development and testing.

    Requires no network calls, no Anthropic API key, and guarantees rapid,
    consistent outputs for testing narrative pipelines and SSE streaming.
    """

    NARRATIVE_TEMPLATES = [
        (
            "The cold river wind cuts through the rotting timbers of the old crossing. ",
            "Beneath the rusted portcullis, brackish water pools against worn stone steps. ",
            "You step into the gloom, lantern held high as distant water droplets echo into the dark.",
        ),
        (
            "Shrouded branches reach down through the twilight fog like crooked fingers. ",
            "A raven takes flight from a fallen boundary stone, its wings cutting through the heavy silence. ",
            "The path ahead turns steep, winding toward the forgotten courtyard of the fortress.",
        ),
        (
            "Embers smolder faintly in the iron brazier near the hall entrance. ",
            "Dust stirs across the threshold where armored guards once stood watch. ",
            "Your breath clouds in the freezing air as you peer into the shadows ahead.",
        ),
        (
            "Rain patters steadily upon the sodden earth, drumming against ruined masonry. ",
            "A faint glimmer of cold blue witchlight flickers in an arched tower window. ",
            "The scent of damp pine and old parchment lingers as you steady yourself and advance.",
        ),
    ]

    def _get_template_index(self, prompt: str) -> int:
        digest = hashlib.md5(prompt.encode("utf-8")).hexdigest()
        return int(digest[:6], 16) % len(self.NARRATIVE_TEMPLATES)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Yield deterministic fantasy prose chunks asynchronously."""
        idx = self._get_template_index(prompt)
        chunks = self.NARRATIVE_TEMPLATES[idx]
        for chunk in chunks:
            await asyncio.sleep(0.01)  # Micro-yield to mirror real async streaming
            yield chunk

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.2,
    ) -> T:
        """Construct a deterministic Pydantic model instance matching response_model."""
        seed = f"{prompt}:{response_model.__name__}"
        return _generate_mock_model(response_model, seed)


def _generate_mock_value(annotation, field_name: str, seed: str):
    """Recursively generate deterministic mock values matching field annotations."""
    h = int(hashlib.sha256(f"{seed}:{field_name}".encode("utf-8")).hexdigest()[:8], 16)
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Union / Optional types (e.g. Optional[str], Union[int, None], str | None)
    if origin in (Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _generate_mock_value(non_none[0], field_name, seed)
        return None

    # List / list types
    if origin in (list, List):
        item_type = args[0] if args else str
        item1 = _generate_mock_value(item_type, f"{field_name}_0", seed)
        item2 = _generate_mock_value(item_type, f"{field_name}_1", seed)
        return [item1, item2]

    # Dict types
    if origin in (dict, Dict):
        return {"note": f"mock_{field_name}"}

    # Literal types
    if origin is Literal:
        return args[h % len(args)]

    # Enum types
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        members = list(annotation)
        return members[h % len(members)]

    # Sub-models (nested BaseModel)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _generate_mock_model(annotation, f"{seed}:{field_name}")

    # Booleans
    if annotation is bool:
        # Default safety, validation, and consistency checks to True
        if any(w in field_name.lower() for w in ("valid", "consistent", "allow", "pass", "success")):
            return True
        return (h % 2) == 0

    # Integers
    if annotation is int:
        if "salience" in field_name.lower():
            return (h % 10) + 1  # 1 to 10 scale
        if "hp" in field_name.lower():
            return (h % 20) - 5  # Realistic HP delta
        return (h % 50) + 1

    # Floats
    if annotation is float:
        return round((h % 100) / 10.0, 2)

    # Strings
    if annotation is str:
        name_lower = field_name.lower()
        if "mood" in name_lower:
            moods = ["Tense", "Wary", "Relieved", "Grim", "Determined"]
            return moods[h % len(moods)]
        if "location" in name_lower:
            locations = ["The Sunken Crossroads", "Ruined Gatehouse", "Foggy Crossing", "High Bastion"]
            return locations[h % len(locations)]
        if "action" in name_lower:
            return "Cautiously scout the passage ahead."
        if "narration" in name_lower or "content" in name_lower or "prose" in name_lower:
            return "The old lantern flickers against damp stone as the passage widens."
        if "fact" in name_lower:
            return f"Fact established: the northern portcullis is chained shut ({h % 100})."
        if "explanation" in name_lower or "reason" in name_lower:
            return "Narrative action is coherent with established world state."
        return f"mock_{field_name}_{h % 1000}"

    return None


def _generate_mock_model(model_cls: Type[T], seed: str) -> T:
    """Instantiate a Pydantic model populated with deterministic mock values."""
    payload = {}
    for name, field in model_cls.model_fields.items():
        # Respect non-None default values if defined
        if field.default is not PydanticUndefined and field.default is not None:
            payload[name] = field.default
        else:
            val = _generate_mock_value(field.annotation, name, seed)
            payload[name] = val
    return model_cls.model_validate(payload)


def get_llm_client(force_mock: bool = False) -> LLMClient:
    """Factory returning the appropriate LLMClient implementation.

    Automatically uses `AnthropicLLMClient` when ANTHROPIC_API_KEY is configured
    in environment/settings. Otherwise returns `MockLLMClient` for seamless,
    zero-dependency local testing and development.
    """
    if not force_mock and settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY.strip():
        return AnthropicLLMClient()
    return MockLLMClient()
