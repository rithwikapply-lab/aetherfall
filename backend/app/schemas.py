"""Pydantic schemas for Aetherfall request/response validation and agent outputs."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthCheckResponse(BaseModel):
    status: str
    app: str
    environment: str
    database_configured: bool


class ItemGain(BaseModel):
    """An item acquired by the player during a turn."""
    name: str
    description: str = ""


class NPCRelationshipDelta(BaseModel):
    """A change in affinity and memory recorded for an NPC."""
    npc_name: str
    delta: int = Field(default=0, description="Relationship score delta (-100 to 100)")
    memory_note: str = Field(default="", description="First-person observation from NPC")


class StateDelta(BaseModel):
    """Structured mutations extracted from narrative turn prose.

    Produced by the State Extraction Agent to update GameSession,
    StoryNode, InventoryItem, and NPC tables atomically.
    """
    hp_change: int = Field(default=0, description="Damage taken or HP restored")
    focus_change: int = Field(default=0, description="Focus expended or regained")
    location: Optional[str] = Field(default=None, description="New location if player moved")
    mood: Optional[str] = Field(default=None, description="Current player mood/disposition")
    items_gained: List[ItemGain] = Field(default_factory=list, description="New items acquired")
    items_lost: List[str] = Field(default_factory=list, description="Names of items consumed or dropped")
    npc_relationship_deltas: List[NPCRelationshipDelta] = Field(
        default_factory=list,
        description="NPC sentiment and memory changes"
    )
    facts_established: List[str] = Field(
        default_factory=list,
        description="New canonical world facts established this turn"
    )


class ContinuityResult(BaseModel):
    """Output from the Continuity Guard checking narration against established world facts."""
    has_contradiction: bool = Field(default=False, description="Whether narration contradicts prior facts")
    contradicting_claim: Optional[str] = Field(default=None, description="The specific sentence in narration that conflicts")
    established_fact: Optional[str] = Field(default=None, description="The established ancestor fact that was violated")
    reason: Optional[str] = Field(default=None, description="Explanation of why this is a continuity contradiction")


class RecalledMemory(BaseModel):
    """An NPC memory retrieved during turn context generation."""
    npc_name: str
    npc_id: str
    memory_id: str
    content: str
    salience: int
    score: float


class TurnResult(BaseModel):
    """Aggregated outcome of a single completed turn across the 4-agent pipeline."""
    session_id: str
    node_id: str
    parent_id: Optional[str]
    turn_number: int
    narration: str
    player_action: Optional[str]
    location: str
    mood: str
    hp: int
    focus: int
    state_delta: StateDelta
    continuity: ContinuityResult
    recalled_memory: Optional[RecalledMemory] = None


# ==============================================================================
# API REQUEST & RESPONSE SCHEMAS
# Using ConfigDict(from_attributes=True) for seamless SQLAlchemy ORM serialization.
# ==============================================================================

class SessionCreateRequest(BaseModel):
    title: Optional[str] = "The Sunken Reach"
    chapter: Optional[str] = "Chapter 1: The Drowned Road"


class SessionCreateResponse(BaseModel):
    id: str
    title: str
    chapter: str
    current_node_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class InventoryItemResponse(BaseModel):
    id: str
    session_id: str
    name: str
    description: str
    acquired_at_node_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class QuestResponse(BaseModel):
    id: str
    session_id: str
    title: str
    status: str
    description: str
    updated_at_node_id: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class NPCResponse(BaseModel):
    id: str
    name: str
    description: str
    relationship_score: int
    relationship_label: str
    model_config = ConfigDict(from_attributes=True)


class SessionStateResponse(BaseModel):
    id: str
    title: str
    chapter: str
    hp: int
    max_hp: int
    focus: int
    max_focus: int
    location: str
    mood: str
    current_node_id: Optional[str] = None
    inventory: List[InventoryItemResponse] = Field(default_factory=list)
    quests: List[QuestResponse] = Field(default_factory=list)
    npcs: List[NPCResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class StoryNodeSummaryResponse(BaseModel):
    id: str
    parent_id: Optional[str] = None
    turn_number: int
    player_action: Optional[str] = None
    narration: str
    location: str
    created_at: Optional[datetime] = None
    status: str = Field(
        default="path",
        description="Node role in tree: 'current', 'path', 'alternate', or 'abandoned'"
    )
    model_config = ConfigDict(from_attributes=True)


class StoryGraphResponse(BaseModel):
    session_id: str
    current_node_id: Optional[str] = None
    nodes: List[StoryNodeSummaryResponse] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class StoryNodeDetailResponse(BaseModel):
    id: str
    session_id: str
    parent_id: Optional[str] = None
    turn_number: int
    player_action: Optional[str] = None
    narration: str
    location: str
    facts: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    status: str = Field(
        default="path",
        description="Node role in tree: 'current', 'path', 'alternate', or 'abandoned'"
    )
    model_config = ConfigDict(from_attributes=True)


class ActionRequest(BaseModel):
    action_text: str
    from_node_id: Optional[str] = None
