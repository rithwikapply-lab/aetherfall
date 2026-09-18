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
from google import genai
from google.genai import types as genai_types
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


class GeminiLLMClient(LLMClient):
    """Production LLM client utilizing Google's Gemini API via the google-genai SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = settings.GOOGLE_API_KEY
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY is required to initialize GeminiLLMClient. "
                "Use MockLLMClient for offline development or testing."
            )
        self.model = model or settings.GEMINI_MODEL or "gemini-flash-lite-latest"
        self._client = genai.Client(api_key=self.api_key)

    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """Stream narrative text deltas from Gemini using generate_content_stream."""
        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_prompt if system_prompt else None,
        )
        stream = await self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.2,
    ) -> T:
        """Force Gemini to return structured output matching response_model using response_schema."""
        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
            response_schema=response_model,
        )

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, response_model):
                return response.parsed
            if isinstance(response.parsed, BaseModel):
                return response_model.model_validate(response.parsed.model_dump())
            if isinstance(response.parsed, dict):
                return response_model.model_validate(response.parsed)

        if getattr(response, "text", None):
            return response_model.model_validate_json(response.text)

        raise ValueError(
            f"Gemini model did not return valid structured output for {response_model.__name__}. "
            f"Response: {response}"
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
        if response_model.__name__ == "StateDelta":
            delta_instance = self._generate_keyword_sensitive_state_delta(prompt, response_model)
            if delta_instance is not None:
                return delta_instance

        if response_model.__name__ == "ContinuityResult":
            if "simulate contradiction" in prompt.lower() or "force contradiction" in prompt.lower():
                return response_model(
                    has_contradiction=True,
                    contradicting_claim="The bridge stood intact above the churning waters.",
                    established_fact="the bridge is out",
                    reason="Narration claims the bridge is intact, violating established fact that the bridge is out."
                )
            return response_model(
                has_contradiction=False,
                contradicting_claim=None,
                established_fact=None,
                reason="Narrative maintains continuity with established world facts."
            )

        seed = f"{prompt}:{response_model.__name__}"
        return _generate_mock_model(response_model, seed)

    def _generate_keyword_sensitive_state_delta(
        self,
        prompt: str,
        response_model: Type[T],
    ) -> Optional[T]:
        """Generate keyword-sensitive state mutations for the StateDelta schema.

        Inspects the prompt text to semantically align mock outputs with player actions:
        - Combat keywords ('attack', 'fight', 'strike', 'hit') -> damage (hp_change < 0).
        - Exploration keywords ('search', 'look', 'examine', 'take') -> items_gained populated.
        - Dialogue keywords ('ask', 'talk', 'tell', 'speak') -> npc_relationship_deltas populated.
        - Otherwise returns None to fall back to generic hash-based generation.
        """
        prompt_lower = prompt.lower()
        h = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)

        combat_kws = ("attack", "fight", "strike", "hit")
        search_kws = ("search", "look", "examine", "take")
        dialogue_kws = ("ask", "talk", "tell", "speak")

        is_combat = any(kw in prompt_lower for kw in combat_kws)
        is_search = any(kw in prompt_lower for kw in search_kws)
        is_dialogue = any(kw in prompt_lower for kw in dialogue_kws)

        if not (is_combat or is_search or is_dialogue):
            return None

        from app.schemas import ItemGain, NPCRelationshipDelta

        if is_combat:
            # Plausible damage range: -1 to -15
            damage = -((h % 15) + 1)
            moods = ["Bruised", "Defiant", "Exhausted", "Adrenaline-fueled", "Grim"]
            return response_model(
                hp_change=damage,
                focus_change=-((h % 5) + 1),
                location=None,
                mood=moods[h % len(moods)],
                items_gained=[],
                items_lost=[],
                npc_relationship_deltas=[],
                facts_established=[f"Violent conflict erupted during turn ({h % 100})."],
            )

        if is_search:
            item_pool = [
                ("Rusted Iron Key", "An ancient key encrusted with river silt."),
                ("Tattered Map Fragment", "A parchment piece outlining forgotten sluice gates."),
                ("Carved Bone Amulet", "An amulet etched with a protective sigil of the Old Guard."),
                ("Brass Pocket Compass", "Its needle spins sluggishly in the presence of ancient magic."),
                ("Vial of Sunken Glow-Moss", "A sealed phial emitting a soft phosphorescent light."),
            ]
            chosen_item = item_pool[h % len(item_pool)]
            return response_model(
                hp_change=0,
                focus_change=0,
                location=None,
                mood="Inquisitive",
                items_gained=[ItemGain(name=chosen_item[0], description=chosen_item[1])],
                items_lost=[],
                npc_relationship_deltas=[],
                facts_established=[f"Discovered {chosen_item[0]} while searching."],
            )

        if is_dialogue:
            npc_names = ["Kael", "the Ferryman", "the Guard Captain", "the Shadowed Scholar"]
            npc_name = "Kael" if "kael" in prompt_lower else npc_names[h % len(npc_names)]
            rel_delta = (h % 11) + 5  # +5 to +15 delta
            memory_templates = [
                f"The traveler spoke with measured respect and listened carefully to {npc_name}.",
                f"{npc_name} noted the traveler's curiosity and felt reassured by their calm demeanor.",
                f"A brief conversation was shared; {npc_name} judged the traveler trustworthy.",
            ]
            note = memory_templates[h % len(memory_templates)]
            return response_model(
                hp_change=0,
                focus_change=0,
                location=None,
                mood="Thoughtful",
                items_gained=[],
                items_lost=[],
                npc_relationship_deltas=[
                    NPCRelationshipDelta(
                        npc_name=npc_name,
                        delta=rel_delta,
                        memory_note=note,
                    )
                ],
                facts_established=[f"Conversed with {npc_name}."],
            )

        return None



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

    Automatically uses:
    1. `AnthropicLLMClient` if ANTHROPIC_API_KEY is configured.
    2. `GeminiLLMClient` if GOOGLE_API_KEY is configured.
    3. `MockLLMClient` otherwise for seamless, zero-dependency local testing and development.
    """
    if not force_mock:
        if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY.strip():
            return AnthropicLLMClient()
        if settings.GOOGLE_API_KEY and settings.GOOGLE_API_KEY.strip():
            return GeminiLLMClient()
    return MockLLMClient()
