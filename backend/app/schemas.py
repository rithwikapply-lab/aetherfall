"""Pydantic schemas for Aetherfall request/response validation and agent outputs."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    hp_delta: int = Field(default=0, description="Health points gained (+) or lost (-) as a result of narrative events")
    focus_delta: int = Field(default=0, description="Focus points gained (+) or lost (-) as a result of narrative events")
    hp_delta_reason: Optional[str] = Field(default=None, description="Concise reasoning for HP delta based on physical harm, hazards, aggression, or recovery")
    focus_delta_reason: Optional[str] = Field(default=None, description="Concise reasoning for Focus delta based on mental effort, judgment, strain, or recovery")
    hp_change: int = Field(default=0, description="Deprecated alias for hp_delta")
    focus_change: int = Field(default=0, description="Deprecated alias for focus_delta")
    location: Optional[str] = Field(default=None, description="New location if player moved")
    mood: Optional[str] = Field(default=None, description="Current player mood/disposition")
    items_gained: List[ItemGain] = Field(default_factory=list, description="New items acquired")
    items_lost: List[str] = Field(default_factory=list, description="Names of items consumed or dropped")
    npc_relationship_deltas: List[NPCRelationshipDelta] = Field(
        default_factory=list,
        description="NPC sentiment and memory changes"
    )
    quests_completed: List[str] = Field(
        default_factory=list,
        description="Titles of active quests completed or resolved this turn"
    )
    facts_established: List[str] = Field(
        default_factory=list,
        description="New canonical world facts established this turn"
    )
    locations_mentioned: List[str] = Field(
        default_factory=list,
        description="Names of distinct real places referenced in narration that the player has not yet physically entered this turn"
    )

    @model_validator(mode="after")
    def sync_deltas(self) -> "StateDelta":
        if self.hp_delta != 0 and self.hp_change == 0:
            self.hp_change = self.hp_delta
        elif self.hp_change != 0 and self.hp_delta == 0:
            self.hp_delta = self.hp_change
        if self.focus_delta != 0 and self.focus_change == 0:
            self.focus_change = self.focus_delta
        elif self.focus_change != 0 and self.focus_delta == 0:
            self.focus_delta = self.focus_change
        return self


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
    turn_count: int = 0
    chapter_number: int = 1
    chapter: str = "Chapter 1: The Drowned Road"
    completed_chapters: List[int] = Field(default_factory=list)
    chapter_advanced: bool = False
    chapter_objective: Optional[str] = None
    is_game_over: bool = False
    game_over_reason: Optional[str] = None
    game_over_summary: Optional[str] = None
    state_delta: StateDelta
    continuity: ContinuityResult
    recalled_memory: Optional[RecalledMemory] = None


# ==============================================================================
# API REQUEST & RESPONSE SCHEMAS
# Using ConfigDict(from_attributes=True) for seamless SQLAlchemy ORM serialization.
# ==============================================================================

class ChapterResponse(BaseModel):
    """Static metadata and objectives for a campaign chapter."""
    number: int
    title: str
    objective: str
    completion_quest_title: str
    completion_quest_description: str
    next_chapter_number: Optional[int] = None


class SessionCreateRequest(BaseModel):
    title: Optional[str] = "The Sunken Reach"
    chapter: Optional[str] = "Chapter 1: The Drowned Road"


class SessionCreateResponse(BaseModel):
    id: str
    title: str
    chapter: str
    chapter_number: int = 1
    completed_chapters: List[int] = Field(default_factory=list)
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
    chapter_number: int = 1
    completed_chapters: List[int] = Field(default_factory=list)
    chapter_objective: Optional[str] = None
    hp: int
    max_hp: int
    focus: int
    max_focus: int
    location: str
    mood: str
    turn_count: int = 0
    is_game_over: bool = False
    game_over_reason: Optional[str] = None
    game_over_summary: Optional[str] = None
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


# ==============================================================================
# WORLD MAP API SCHEMAS
# ==============================================================================

class LocationNode(BaseModel):
    """A place the player has visited or that has been mentioned in narration."""
    id: str = Field(description="Slugified location name used as stable identifier")
    name: str = Field(description="Display name of the location")
    description: str = Field(description="Short excerpt from the narration at first arrival")
    chapter_number: int = Field(description="Chapter active when this location was first reached/mentioned")
    visited_at_turn: int = Field(description="Turn number when this location was first reached (visited) or mentioned")
    visited: bool = Field(description="True if the player physically traveled here; False if only mentioned in narration")
    is_current: bool = Field(default=False, description="True if this is the player's current location")


class LocationEdge(BaseModel):
    """A travel connection between two visited locations along the active story path."""
    source_id: str = Field(description="Slugified name of the origin location")
    target_id: str = Field(description="Slugified name of the destination location")


class WorldMapResponse(BaseModel):
    """Complete world-map data derived from the active story-node chain."""
    session_id: str
    current_location: str
    nodes: List[LocationNode] = Field(default_factory=list)
    edges: List[LocationEdge] = Field(default_factory=list)
