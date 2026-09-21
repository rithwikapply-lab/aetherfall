# Aetherfall

> **An AI Dungeon Master engine where the world is a relational database, not a chat transcript.**

Aetherfall is an interactive dark-fantasy narrative engine built with **FastAPI**, **SQLAlchemy 2.0 (Async ORM)**, and **React**. Rather than appending player prompts and model responses into an ever-expanding conversational context window, Aetherfall models world state as discrete, normalized database entities (`GameSession`, `StoryNode`, `InventoryItem`, `Quest`, `NPC`, and `NPCMemoryEntry`). 

Player choices form an explicit directed tree of `StoryNode` records linked by self-referential `parent_id` foreign keys. This architectural foundation enables branching timeline forks, strict canon continuity enforcement, explainable NPC memory retrieval, and a dynamic physical world map—capabilities that cannot be reliably achieved with single-prompt chatbot wrappers.

---

## 1. Why A Relational Database Over Chat Transcripts?

Most LLM-based interactive fiction applications operate as "chat wrappers": every turn appends the player's action and the model's prose to an ongoing text transcript passed into the next generation. This pattern degrades under three fundamental architectural failure modes:

1. **Context Window Degradation & Token Inflation**: History length grows quadratically with turn count, quickly hitting model context limits, ballooning latency, and driving up inference costs.
2. **Context Drift & Hallucinations**: World facts established 20 turns prior dilute among thousands of tokens. The model forgets inventory items, revives deceased characters, or contradicts established canon because facts are merely unindexed tokens in a prompt string.
3. **Impossibility of Branching**: In a flat transcript, exploring an alternative choice requires destructively truncating history. You cannot maintain simultaneous alternate branches or rewind to an earlier fork point without corrupting the timeline.

In Aetherfall, **the database is the single source of truth**:
- **Branching is an Explicit Tree**: Every turn creates an immutable `StoryNode` with a `parent_id`. Replaying from an earlier turn forks a sibling node under that ancestor, preserving superseded branches in the database without data loss.
- **State Mutations are Atomic**: HP, Focus, inventory mutations, quest progression, and NPC sentiments are extracted via structured tool calling into a Pydantic `StateDelta` and committed atomically inside an ACID transaction.
- **Canon Continuity is Enforced**: A dedicated Continuity Guard traverses the ancestor chain of the active branch to detect and reject narrative contradictions before committing to the database.
- **Memory is Queryable & Explainable**: NPCs maintain discrete memory records scored by lexical overlap, recency decay, and salience, rather than relying on an LLM to attend over a noisy transcript.
- **Physical Travel is Separated from Narrative Flow**: A distinct physical World Map graph is derived from active-branch location transitions, separate from the narrative story tree.

---

## 2. Quickstart

Aetherfall is designed to run **100% offline with zero external dependencies and zero API keys** using `MockLLMClient` and an automatic SQLite database, while providing production-ready support for PostgreSQL 16, Redis 7, and live LLM generation with either Google Gemini or Anthropic Claude.

### Option A: Local Dev Mode (Zero Dependencies, Offline Mock Mode)

#### 1. Backend (FastAPI + SQLite)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
*Note: SQLite automatically initializes `backend/aetherfall.db` with all tables and schema migrations on first startup. No manual migration or seed commands required.*

#### 2. Frontend (React + Vite)
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). You can immediately begin a campaign, take turns, stream prose, inspect the story DAG, view the physical world map, and fork branches without needing an API key or internet connection.

---

### Option B: Docker Compose (PostgreSQL 16 + Redis 7 + API Container)

To run the containerized production-ready stack:

```bash
# Optional: Export an API key to enable live LLM generation.
# Option 1: Google Gemini (Free tier available on Google AI Studio)
export GOOGLE_API_KEY="your-gemini-api-key"
export GEMINI_MODEL="gemini-flash-lite-latest"

# Option 2: Anthropic Claude (Takes precedence if both are set)
# export ANTHROPIC_API_KEY="your-anthropic-api-key"
# export LLM_MODEL="claude-sonnet-4-5"

# If both are omitted or empty, the engine automatically runs MockLLMClient.
docker compose up --build -d
```

The `api` container waits for PostgreSQL's healthcheck (`pg_isready`) before launching, exposes port `8000`, and runs uvicorn against `postgresql+asyncpg://`.

To hit the containerized API:
```bash
curl -s http://127.0.0.1:8000/api/health
```

---

## 3. Architecture & Systems Overview

### A. The Four-Agent Turn Pipeline

Every player turn executes through an orchestrated four-agent pipeline implemented in [`backend/app/agents/pipeline.py`](backend/app/agents/pipeline.py):

```
                       Player Action
                             │
                             ▼
            ┌─────────────────────────────────┐
            │       1. NPC Memory Agent       │
            │  (Lexical Jaccard + Recency)    │
            └────────────────┬────────────────┘
                             │ Injects relevant recalled memory
                             ▼
            ┌─────────────────────────────────┐
            │        2. Narrator Agent        │
            │ (SSE Streaming Prose Generation)│
            └────────────────┬────────────────┘
                             │ Complete narrative prose
                             ▼
            ┌─────────────────────────────────┐
            │    3. State-Extraction Agent    │
            │ (Structured StateDelta Tooling) │
            └────────────────┬────────────────┘
                             │ Atomically applies state mutations
                             ▼
            ┌─────────────────────────────────┐
            │    4. Continuity Guard Agent    │
            │ (Tier 1 Bypass / Tier 2 Verify) │
            └────────────────┬────────────────┘
                             │
                             ▼
            Database Commit & Story Node Creation
            (Active branch, story tree, and map updated)
```

1. **NPC Memory Agent** ([`backend/app/agents/npc_memory.py`](backend/app/agents/npc_memory.py)):
   Inspects all NPCs present in the scene. Scores their memory entries against the player's action using tokenized Jaccard similarity, normalized salience, and recency decay. If the highest score clears the threshold (default: 0.25), the recalled memory is injected into the Narrator's prompt.
2. **Narrator Agent** ([`backend/app/agents/narrator.py`](backend/app/agents/narrator.py)):
   Generates rich narrative prose chunk-by-chunk. Streamed live to the browser via Server-Sent Events (SSE) over `POST /api/sessions/{id}/action`.
3. **State-Extraction Agent** ([`backend/app/agents/state_extractor.py`](backend/app/agents/state_extractor.py)):
   Analyzes the completed narration against the player's action using forced structured output (`StateDelta` schema). Atomically applies state mutations in SQLAlchemy:
   - Updates player HP, focus, mood, and location on `GameSession`.
   - Adds newly acquired `InventoryItem` records or marks dropped items.
   - Adjusts NPC affinity scores and appends new `NPCMemoryEntry` records.
   - Evaluates active quest objectives and advances chapters upon quest completion.
   - Appends newly established canon facts and unvisited locations mentioned to the new `StoryNode`.
4. **Continuity Guard Agent** ([`backend/app/agents/continuity_guard.py`](backend/app/agents/continuity_guard.py)):
   Traverses the parent chain from the new node back to root to collect all established canon facts for this branch. Evaluates the narration using a **two-tier architecture**:
   - **Tier 1 (Short-Circuit)**: If zero ancestor facts exist (common on opening turns), bypasses the LLM entirely and returns `has_contradiction=False` with zero latency.
   - **Tier 2 (Structured Verification)**: If canon facts exist, runs a structured schema check (`ContinuityResult`) to detect direct contradictions, returning the violating claim, the violated fact, and the reasoning.

---

### B. The Branching Mechanism (`parent_id` / `from_node_id`)

The story graph is an explicit directed tree where every node points to its ancestor:

```
[Root: Turn 0]
      │
[Node 1: Turn 1 (Sunken Crossroads)]
      ├───► [Node 2: Turn 2 (Ruined Gatehouse)] ───► [Node 3: Turn 3 (Crypts)] (Abandoned Branch)
      │
      └───► [Node 4: Turn 2 (Hidden Sluice)] (Active Leaf Node)
```

1. **Standard Turn**: When continuing from the active leaf, `target_parent_id = session.current_node_id`. The new node is parented to the current leaf.
2. **Replay Turn**: In the Story Graph UI ([`frontend/src/components/GraphScreen.jsx`](frontend/src/components/GraphScreen.jsx)), clicking any ancestor node and selecting **"Replay from here"** sends `POST /api/sessions/{id}/action` with `from_node_id = <ancestor_id>`.
3. **Tree Forking**: The pipeline sets `parent_id = from_node_id`, creates a new child under that ancestor, and updates `session.current_node_id` to point at the new branch.
4. **Dynamic Node Status Classification**: In `GET /api/sessions/{id}/graph` ([`backend/app/api/sessions.py`](backend/app/api/sessions.py)), the backend walks the tree to classify every node:
   - `current`: The active leaf node (`session.current_node_id`).
   - `path`: Ancestor nodes on the direct line between root and `current`.
   - `alternate`: Direct siblings at fork points off the active path.
   - `abandoned`: Deeper descendants of superseded, inactive branches.

---

### C. Physical World Map & Minimap System

While the **Story Graph** tracks narrative choice branches, the **World Map** tracks *physical geographic travel* through the world:

- **Graph Derivation (`GET /api/sessions/{id}/map`)**:
  Implemented in [`backend/app/api/sessions.py`](backend/app/api/sessions.py). Walks the active branch from root to the current leaf:
  - **Visited Nodes**: Unique locations physically visited across active turns, attributed to the chapter they were first discovered in.
  - **Sequential Travel Edges**: Directed edges created *strictly* when consecutive turns involve a physical transition between distinct locations (`source_id -> target_id`).
  - **Mentioned / Unvisited Nodes**: Extracted from `story_nodes.locations_mentioned` (places spoken of in narration or dialogue but not yet physically reached). Rendered as distinct dashed-outline nodes.
- **Hooke's-Law Force-Directed Layout**:
  Implemented in pure SVG/JS in [`frontend/src/components/WorldMapScreen.jsx`](frontend/src/components/WorldMapScreen.jsx). Solves equilibrium node positions using:
  - **Pairwise Repulsion**: Coulomb-like repulsion ($F_{rep} = \frac{k_{rep}}{d^2}$) keeping all nodes well separated.
  - **Edge Spring Attraction**: Hooke's-law spring force ($F_{spr} = k_{spr} \cdot (d - L_{0})$) with rest length $L_0 = 150\text{px}$, keeping connected locations at a readable distance without overlapping.
  - **Center Gravity**: Subtle gravitational pull towards canvas center ($F_{cen} = k_{cen} \cdot (c - p)$), preventing unvisited or disconnected nodes from drifting to canvas boundaries.
- **Sidebar Minimap**:
  Embedded in the main gameplay screen ([`frontend/src/components/MainScreen.jsx`](frontend/src/components/MainScreen.jsx)). Dynamically renders the player's immediate geographic neighbourhood (current location + immediate neighbours with pulsing ring) and expands to the full map on click.

---

### D. Campaign Progression & Four-Chapter Architecture

Campaign progression is driven by canonical chapter specifications in [`backend/app/chapters.py`](backend/app/chapters.py):
- **Chapter 1: The Drowned Road** (Objective: Cross the flooded highway; completion quest: *"Cross the Drowned Valley"*)
- **Chapter 2: The Ghost-Catcher's Ledger** (Objective: Find Kael; completion quest: *"Find Kael"*)
- **Chapter 3: The Salt-Bound Wraiths** (Objective: Deal with the wraiths in the flood; completion quest: *"Confront the Wraiths"*)
- **Chapter 4: The Source of the Deluge** (Objective: Reach the source of the flooding; completion quest: *"Reach the Source"*)

When the State-Extraction Agent identifies that a chapter's completion quest has been achieved, the pipeline automatically advances `session.chapter_number`, records the completed chapter in `completed_chapters`, seeds the next chapter's primary quest into the relational database, and triggers a chapter advancement interstitial in the UI. Completing Chapter 4 transitions the session to victory.

---

### E. Authoritative Session Resume (Zero Client-Side State)

Aetherfall strictly enforces that **game state never lives in browser storage**:
- Browser `localStorage` holds **only** an opaque identifier plus cosmetic button hints:
  ```json
  {
    "id": "87d18541-3cfe-4553-8295-b0abfeba4c27",
    "title": "The Chronicles of Aetherfall",
    "chapter": "Chapter 2: The Ghost-Catcher's Ledger"
  }
  ```
- *No HP, focus, location coordinates, turn counts, inventory, or game-over flags are ever stored in `localStorage`.*
- Clicking **"Resume Campaign"** triggers an asynchronous `GET /api/sessions/{id}/state` fetch to retrieve authoritative world state directly from database rows. If the session no longer exists in the database (e.g. database purge), the client automatically purges the dead pointer and prompts the player to begin anew.

---

## 4. Why Lexical Memory Over Vector Embeddings?

The NPC Memory Agent uses pure-Python lexical scoring (Jaccard similarity on non-stopword tokens + normalized salience + recency decay) rather than a vector database or embedding service.

This is a **deliberate architectural decision**, not a shortcut:

1. **Deterministic Explainability**: Neural embeddings produce opaque cosine similarity floats that cannot explain *why* a memory was triggered. In Aetherfall, memory recall is completely explainable: you can inspect the exact token overlap between `"river bridge rations"` in the player's action and the NPC's memory record.
2. **Zero External Dependencies**: Running a vector database requires embedding APIs, network latency, or local embedding models (e.g. PyTorch / sentence-transformers). Pure lexical scoring runs entirely offline with zero dependencies, executing in sub-millisecond time.
3. **Comprehensive Unit Testing**: Pure lexical scoring allows the entire memory retrieval, thresholding, and recency decay pipeline to be tested in standard unit tests without spinning up vector stores or mocking embedding calls.
4. **Clean Swap Boundary**: The module exposes clean functions (`retrieve_relevant` and `best_recall`). If semantic embedding search is desired in the future, only the internal `score_memory` function needs modification—the four-agent pipeline and calling code remain completely unchanged.

---

## 5. Automated Test Suite & Architecture Proofs

The backend includes a comprehensive **55-test suite** in [`backend/tests/`](backend/tests/) running via `pytest` and `pytest-asyncio`. Every test executes with **zero network calls and zero API keys** against `MockLLMClient` and ephemeral per-test SQLite databases in under 1.5 seconds.

```bash
cd backend
.venv/bin/pytest -v
============================== 55 passed in 1.44s ==============================
```

### Test Coverage Breakdown

| Test File | Count | Focus & Verified Behavior |
| :--- | :---: | :--- |
| [`test_api_game_flow.py`](backend/tests/test_api_game_flow.py) | **10** | Session creation, state retrieval, SSE streaming action execution, state delta updates, story graph DAG node statuses (`current`, `path`, `alternate`, `abandoned`), StoryNode detail endpoint, 404 error handling for unknown session/node IDs, and turn rejection on game-over sessions. |
| [`test_chapters.py`](backend/tests/test_chapters.py) | **6** | `GET /api/chapters` API endpoint, narrator prompt injection of chapter objectives, automatic chapter advancement upon quest completion, non-advancement for standard actions, Chapter 4 completion triggering victory, and `completed_chapters` history accumulation. |
| [`test_continuity_guard.py`](backend/tests/test_continuity_guard.py) | **4** | Tier 1 short-circuit bypass on branches with 0 ancestor facts (verified with `ExplosiveLLMClient`), Tier 2 structured contradiction detection, validation of coherent narrative prose, and recursive ancestor fact hierarchy traversal. |
| [`test_llm_client.py`](backend/tests/test_llm_client.py) | **12** | Defaulting to `MockLLMClient`, mock streaming, mock structured output, Anthropic client interface, Google Gemini client interface, provider precedence resolution, Gemini streaming/structured mocks, and keyword-based `MockStateDelta` generation (combat, search, dialogue, neutral). |
| [`test_models.py`](backend/tests/test_models.py) | **2** | SQLAlchemy model lifecycle, eager relationship loading (`inventory`, `quests`, `npcs`, `memories`), game over lifecycle, and turn count tracking. |
| [`test_npc_memory.py`](backend/tests/test_npc_memory.py) | **6** | Lexical overlap ranking, zero overlap returning zero score, recency decay diminishing older memory scores, threshold filtering (returns `None` below 0.25), recall matching above threshold, and multi-NPC scene best recall selection. |
| [`test_pipeline.py`](backend/tests/test_pipeline.py) | **3** | Full turn execution keyword flow, timeline branching/replay from an ancestor node (`from_node_id`), and action rejection on game-over sessions. |
| [`test_state_extractor.py`](backend/tests/test_state_extractor.py) | **8** | StateDelta extraction for combat, search, and dialogue actions; database mutation application; health and focus attrition and clamping [0, max]; game over death when HP reaches 0; game over collapse when Focus reaches 0; and HP death priority when both reach 0 simultaneously. |
| [`test_world_map.py`](backend/tests/test_world_map.py) | **4** | World map node and edge derivation from active path StoryNodes, multi-chapter node color attribution, single-location starting state handling, and distinct rendering for unvisited mentioned locations. |

---

## 6. Known Limitations & Trade-offs

In the spirit of transparent engineering documentation:

1. **Client-Side Synchronous Force Layout**: The force-directed graph calculation in `WorldMapScreen.jsx` runs synchronously in React's `useMemo` (80 iterations of pairwise repulsion and spring forces). For typical campaigns (up to 30 locations), it executes in under 2ms. However, for massive campaigns with hundreds of locations, an $O(V^2 + E)$ synchronous simulation would block the main UI thread and would require offloading to a Web Worker or stepping through an asynchronous requestAnimationFrame simulation loop.
2. **Active-Path Only Cartography**: `GET /api/sessions/{id}/map` derives visited locations and travel edges *strictly* from the active leaf's direct ancestor chain (`path` StoryNodes). If a player explores a location on Branch A, then rewinds to Turn 1 and takes Branch B, locations visited only in Branch A are excluded from the current map view. A global "omniscient" map encompassing abandoned branches is not currently aggregated.
3. **Orbiting Unvisited Locations**: Mentioned-but-unvisited locations (e.g. rumors of "Bone Quay") are derived without known topological coordinates or edges, so they sit as unanchored nodes in the outer force field rather than attaching to a defined road.
4. **MockLLMClient Narration is Deterministic**: In offline mode, `MockLLMClient` generates templated, deterministic prose derived from action hashes and keywords. It proves that async generators, SSE streaming, and structured schema extraction work end-to-end, but lacks the emergent prose of a live foundation model.
5. **Redis is Provisioned But Unwired**: Redis 7 is configured in `docker-compose.yml` to demonstrate multi-container orchestration, but session caching and pub/sub message queuing are not yet wired into the FastAPI backend (state currently resides directly in PostgreSQL/SQLite).
6. **No Multi-Tenant Authentication**: Sessions are partitioned by UUID, but there is no user login system or row-level access control.
7. **The CRLF SSE Parser Bug**: During early playtesting, `buffer.split('\n\n')` failed on Windows/HTTP-standard `\r\n\r\n` line endings from uvicorn, causing chunks to buffer indefinitely before crashing JSON parsing. The bug was resolved by updating the client parser to scan for `/\r?\n\r?\n/` boundaries.

---

## 7. Resume & Portfolio Highlights

- **Relational World State Architecture**: Engineered a database-backed game engine in FastAPI and SQLAlchemy 2.0 (Async ORM) where world state, inventory, quests, and branching history reside in normalized SQL tables rather than an unindexed LLM chat transcript; verified timeline forking via [`backend/tests/test_pipeline.py`](backend/tests/test_pipeline.py).
- **Physical World Map & Force-Directed SVG Engine**: Built a dynamic travel cartography system that parses physical transitions across active `StoryNode` chains, calculates Hooke's-law spring physics with equilibrium lengths and center gravity in pure React SVG ([`frontend/src/components/WorldMapScreen.jsx`](frontend/src/components/WorldMapScreen.jsx)), and renders a live sidebar minimap ([`backend/tests/test_world_map.py`](backend/tests/test_world_map.py)).
- **Two-Tier LLM Continuity Guard**: Designed a cost- and latency-optimized verification agent that short-circuits LLM calls on opening turns with zero ancestor facts; proved zero LLM invocation using an explosive mock in [`backend/tests/test_continuity_guard.py`](backend/tests/test_continuity_guard.py).
- **Four-Chapter Campaign Progression System**: Implemented canonical chapter objectives, quest-driven transitions, and victory conditions in [`backend/app/chapters.py`](backend/app/chapters.py), driving chapter-aware narrator prompting and dynamic world map coloring ([`backend/tests/test_chapters.py`](backend/tests/test_chapters.py)).
- **Explainable Lexical Memory Scoring**: Designed a pure-Python NPC memory retrieval system combining tokenized non-stopword Jaccard overlap, salience normalization, and recency decay without external vector database dependencies in [`backend/tests/test_npc_memory.py`](backend/tests/test_npc_memory.py).
- **Custom SSE-Over-POST Transport**: Hand-crafted a streaming Server-Sent Events parser over HTTP POST in [`frontend/src/api/client.js`](frontend/src/api/client.js) adhering to the W3C single-leading-space rule, handling `\r\n\r\n` boundary edge cases without corrupting whitespace.
- **Multi-Provider LLM Abstraction with Native Structured Outputs**: Implemented a unified `LLMClient` supporting Anthropic Claude, Google Gemini, and offline `MockLLMClient` with schema-enforced Pydantic output validation and automated runtime fallback in [`backend/tests/test_llm_client.py`](backend/tests/test_llm_client.py).
