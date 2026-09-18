"""SQLAlchemy database models for Aetherfall.

Phase 1 placeholder. Future phases will define:
- Campaign: Campaign metadata, world seed, ruleset configuration
- TurnNode: Tree-structured story graph (parent_id, branch_path, narrative, action)
- EntityState: Structured world entities (characters, items, locations, faction affinity)
- WorldDelta: State mutation records per turn for deterministic rewind/replay
"""

from app.database import Base

# Model definitions will be implemented in subsequent phases.
