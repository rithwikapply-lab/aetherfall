"""SQLAlchemy 2.0 async ORM models for Aetherfall.

==============================================================================
ASYNC SQLALCHEMY & EAGER LOADING CONVENTION (MissingGreenlet Prevention)
==============================================================================
In SQLAlchemy's async ORM, accessing a lazy-loaded relationship outside of an
active session or synchronous greenlet context raises `MissingGreenlet`.
To prevent this error across the application:
1. `Base` inherits from `AsyncAttrs` to support `await obj.awaitable_attrs.rel`
   if async lazy loading is needed.
2. In querying pipelines (e.g. Memory Agent querying NPCs), queries MUST
   eagerly load required relationships using `selectinload`:
       stmt = select(NPC).where(NPC.id == npc_id).options(selectinload(NPC.memories))
       npc = (await session.execute(stmt)).scalar_one()
       # npc.memories is now populated in memory and safe to read synchronously.
==============================================================================
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from app.database import Base


class GameSession(Base):
    """Represents a player's ongoing interactive fiction game session.

    Holds denormalized current-state attributes (hp, location, focus, mood)
    for fast frontend reads, while pointing to the active leaf of the
    branching StoryNode tree via `current_node_id`.
    """

    __tablename__ = "game_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(
        String(255),
        default="Untitled Campaign"
    )
    chapter: Mapped[str] = mapped_column(
        String(255),
        default="Chapter 1: The Drowned Road"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    current_node_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("story_nodes.id", use_alter=True, name="fk_game_sessions_current_node_id"),
        nullable=True
    )

    # Denormalized "current state" fields for fast O(1) status queries by frontend
    hp: Mapped[int] = mapped_column(Integer, default=100)
    max_hp: Mapped[int] = mapped_column(Integer, default=100)
    focus: Mapped[int] = mapped_column(Integer, default=50)
    max_focus: Mapped[int] = mapped_column(Integer, default=50)
    location: Mapped[str] = mapped_column(String(255), default="The Drowned Road")
    mood: Mapped[str] = mapped_column(String(100), default="Tense")
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    # Game-over state
    is_game_over: Mapped[bool] = mapped_column(Boolean, default=False)
    game_over_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    game_over_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    nodes: Mapped[list["StoryNode"]] = relationship(
        "StoryNode",
        back_populates="session",
        foreign_keys="[StoryNode.session_id]",
        cascade="all, delete-orphan"
    )
    current_node: Mapped[Optional["StoryNode"]] = relationship(
        "StoryNode",
        foreign_keys=[current_node_id],
        post_update=True
    )
    npcs: Mapped[list["NPC"]] = relationship(
        "NPC",
        back_populates="session",
        cascade="all, delete-orphan"
    )
    inventory: Mapped[list["InventoryItem"]] = relationship(
        "InventoryItem",
        back_populates="session",
        cascade="all, delete-orphan"
    )
    quests: Mapped[list["Quest"]] = relationship(
        "Quest",
        back_populates="session",
        cascade="all, delete-orphan"
    )


class StoryNode(Base):
    """Represents a single turn in the branching story graph.

    Forms an immutable tree structure via self-referential `parent_id`.
    Replaying an earlier decision creates a new child under that ancestor node,
    forking history rather than overwriting it.
    """

    __tablename__ = "story_nodes"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True
    )
    turn_number: Mapped[int] = mapped_column(
        Integer,
        default=0
    )
    player_action: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    narration: Mapped[str] = mapped_column(
        Text,
        default=""
    )
    location: Mapped[str] = mapped_column(
        String(255),
        default=""
    )
    facts: Mapped[list[str]] = mapped_column(
        JSON,
        default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    session: Mapped["GameSession"] = relationship(
        "GameSession",
        back_populates="nodes",
        foreign_keys=[session_id]
    )
    parent: Mapped[Optional["StoryNode"]] = relationship(
        "StoryNode",
        remote_side=[id],
        back_populates="children",
        foreign_keys=[parent_id]
    )
    children: Mapped[list["StoryNode"]] = relationship(
        "StoryNode",
        back_populates="parent",
        foreign_keys=[parent_id],
        cascade="all, delete-orphan"
    )


class InventoryItem(Base):
    """Items held by the player during a campaign session."""

    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text,
        default=""
    )
    acquired_at_node_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    session: Mapped["GameSession"] = relationship(
        "GameSession",
        back_populates="inventory"
    )
    acquired_at_node: Mapped[Optional["StoryNode"]] = relationship(
        "StoryNode",
        foreign_keys=[acquired_at_node_id]
    )


class Quest(Base):
    """Tracks narrative objectives and quest state progression."""

    __tablename__ = "quests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="active"  # "active" | "completed" | "failed"
    )
    description: Mapped[str] = mapped_column(
        Text,
        default=""
    )
    updated_at_node_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    session: Mapped["GameSession"] = relationship(
        "GameSession",
        back_populates="quests"
    )
    updated_at_node: Mapped[Optional["StoryNode"]] = relationship(
        "StoryNode",
        foreign_keys=[updated_at_node_id]
    )


class NPC(Base):
    """Non-player character with dynamic affinity score and personality."""

    __tablename__ = "npcs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text,
        default=""
    )
    relationship_score: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # Relationships
    session: Mapped["GameSession"] = relationship(
        "GameSession",
        back_populates="npcs"
    )
    memories: Mapped[list["NPCMemoryEntry"]] = relationship(
        "NPCMemoryEntry",
        back_populates="npc",
        cascade="all, delete-orphan"
    )

    @property
    def relationship_label(self) -> str:
        """Map numeric score (-100 to 100) to human-readable sentiment label.

        Keeps the score-to-label translation in a single canonical place to avoid
        drift between the API layer and the frontend.
        """
        if self.relationship_score < -50:
            return "Hostile"
        elif self.relationship_score < -10:
            return "Wary"
        elif self.relationship_score <= 10:
            return "Neutral"
        elif self.relationship_score <= 50:
            return "Friendly"
        else:
            return "Devoted"


class NPCMemoryEntry(Base):
    """Memory entry formed by an NPC on a specific turn node."""

    __tablename__ = "npc_memory_entries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    npc_id: Mapped[str] = mapped_column(
        ForeignKey("npcs.id", ondelete="CASCADE"),
        nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    node_id: Mapped[str] = mapped_column(
        ForeignKey("story_nodes.id", ondelete="CASCADE"),
        nullable=False
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    salience: Mapped[int] = mapped_column(
        Integer,
        default=5
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    # Relationships
    npc: Mapped["NPC"] = relationship(
        "NPC",
        back_populates="memories"
    )
    session: Mapped["GameSession"] = relationship(
        "GameSession"
    )
    node: Mapped["StoryNode"] = relationship(
        "StoryNode"
    )
