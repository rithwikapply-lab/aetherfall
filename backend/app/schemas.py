"""Pydantic schemas for Aetherfall request/response validation and agent outputs."""

from typing import List, Optional
from pydantic import BaseModel, Field


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
