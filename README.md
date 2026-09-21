# Aetherfall

> **An AI Dungeon Master engine where the world is a relational database, not a chat transcript.**

Aetherfall is an interactive dark-fantasy game engine built with **FastAPI**, **SQLAlchemy 2.0 (Async ORM)**, and **React**. Most LLM text games maintain world state by feeding an ever-growing conversation history back into the prompt on each turn. Aetherfall instead models the world using relational database tables (`GameSession`, `StoryNode`, `InventoryItem`, `Quest`, `NPC`, and `NPCMemoryEntry`).

Player choices are stored as a directed tree of `StoryNode` rows linked by self-referential `parent_id` foreign keys. Structuring state this way makes timeline branching, canon contradiction checking, explainable NPC memory retrieval, and physical world map derivation straightforward database operations rather than prompt engineering problems.

---

## 1. Why A Relational Database Over Chat Transcripts?

Most LLM interactive fiction tools work as chat wrappers: each turn appends the player's action and the model's response to an ongoing text transcript, then sends the whole transcript back to the model on the next turn. That approach breaks down in three concrete ways as a game goes on:

1. **Context Window & Latency Growth**: The prompt grows with every turn. Longer turns mean higher token counts, higher per-turn API costs, and noticeably slower response times.
2. **Context Dilution & Hallucinations**: World facts established 20 turns earlier get buried under thousands of tokens of intervening prose. Without explicit tracking, models drop inventory items, contradict dead NPCs, or forget earlier plot events because the facts only exist as unstructured text in context.
3. **Destructive Branching**: With a flat transcript, exploring an alternate choice requires truncating conversation history back to the decision point. Superseded paths are lost, and you cannot easily inspect or switch between divergent branches.

Aetherfall treats database tables—not the model's context window—as the source of truth for the game world:
- **Explicit Branching Tree**: Each turn inserts an immutable `StoryNode` pointing to its `parent_id`. Branching from an earlier turn creates a new sibling node under that ancestor, leaving superseded branches intact in the database.
- **Atomic State Mutations**: Player HP, focus, inventory changes, quest states, and NPC attitudes are extracted from narration into a validated Pydantic `StateDelta` schema, then committed in a single database transaction.
- **Canon Continuity Checks**: Before committing a turn, a Continuity Guard walks the active branch's ancestor nodes in the database to verify new narration doesn't contradict established facts.
- **Queryable NPC Memory**: Rather than asking the model to recall earlier interactions from raw prose, NPCs store distinct memory rows scored on lexical overlap, recency, and salience.
- **Separation of Physical and Narrative Graphs**: Narrative choices live in the `StoryNode` tree, while physical geographic movement is computed separately into a travel graph for the World Map.

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
  - **Pairwise Repulsion**: Coulomb-like node repulsion where repulsive force falls off with the square of the distance, keeping unrelated locations well separated.
  - **Edge Spring Attraction**: Hooke's-law spring attraction along travel edges with a 150px rest length, pulling connected locations toward a readable spacing without overlapping.
  - **Center Gravity**: A weak centering force proportional to displacement from canvas midpoint, preventing unvisited or disconnected nodes from drifting off-screen.
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
2. **Zero External Dependencies**: Running a vector database requires embedding APIs, network latency, or local embedding models (e.g. PyTorch / sentence-transformers). Pure lexical scoring runs entirely offline in pure Python with zero external service dependencies or embedding latency.
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

Engineering trade-offs and known constraints in the current implementation:

1. **Client-Side Synchronous Force Layout**: The force-directed graph calculation in `WorldMapScreen.jsx` runs synchronously in React's `useMemo` (80 iterations of pairwise repulsion and spring forces). At typical campaign scales (up to 30 locations), layout completes synchronously within a single render frame without noticeable stutter. However, for massive graphs with hundreds of locations, an O(V² + E) synchronous simulation would block the main UI thread and would require offloading to a Web Worker or stepping through an asynchronous requestAnimationFrame loop.
2. **Active-Path Only Cartography**: `GET /api/sessions/{id}/map` derives visited locations and travel edges *strictly* from the active leaf's direct ancestor chain (`path` StoryNodes). If a player explores a location on Branch A, then rewinds to Turn 1 and takes Branch B, locations visited only in Branch A are excluded from the current map view. A global "omniscient" map encompassing abandoned branches is not currently aggregated.
3. **Orbiting Unvisited Locations**: Mentioned-but-unvisited locations (e.g. rumors of "Bone Quay") are derived without known topological coordinates or edges, so they sit as unanchored nodes in the outer force field rather than attaching to a defined road.
4. **MockLLMClient Narration is Deterministic**: In offline mode, `MockLLMClient` generates templated, deterministic prose derived from action hashes and keywords. It proves that async generators, SSE streaming, and structured schema extraction work end-to-end, but lacks the emergent prose of a live foundation model.
5. **Redis is Provisioned But Unwired**: Redis 7 is configured in `docker-compose.yml` to demonstrate multi-container orchestration, but session caching and pub/sub message queuing are not yet wired into the FastAPI backend (state currently resides directly in PostgreSQL/SQLite).
6. **No Multi-Tenant Authentication**: Sessions are partitioned by UUID, but there is no user login system or row-level access control.

---

## 7. Resume & Portfolio Highlights

- **Relational World State Architecture**: Engineered a database-backed game engine in FastAPI and SQLAlchemy 2.0 (Async ORM) where world state, inventory, quests, and branching history reside in normalized SQL tables rather than an unindexed LLM chat transcript; verified timeline forking via [`backend/tests/test_pipeline.py`](backend/tests/test_pipeline.py).
- **Physical World Map & Force-Directed SVG Engine**: Built a dynamic travel cartography system that parses physical transitions across active `StoryNode` chains, calculates Hooke's-law spring physics with equilibrium lengths and center gravity in pure React SVG ([`frontend/src/components/WorldMapScreen.jsx`](frontend/src/components/WorldMapScreen.jsx)), and renders a live sidebar minimap ([`backend/tests/test_world_map.py`](backend/tests/test_world_map.py)).
- **Two-Tier LLM Continuity Guard**: Designed a cost- and latency-optimized verification agent that short-circuits LLM calls on opening turns with zero ancestor facts; proved zero LLM invocation using an explosive mock in [`backend/tests/test_continuity_guard.py`](backend/tests/test_continuity_guard.py).
- **Four-Chapter Campaign Progression System**: Implemented canonical chapter objectives, quest-driven transitions, and victory conditions in [`backend/app/chapters.py`](backend/app/chapters.py), driving chapter-aware narrator prompting and dynamic world map coloring ([`backend/tests/test_chapters.py`](backend/tests/test_chapters.py)).
- **Explainable Lexical Memory Scoring**: Designed a pure-Python NPC memory retrieval system combining tokenized non-stopword Jaccard overlap, salience normalization, and recency decay without external vector database dependencies in [`backend/tests/test_npc_memory.py`](backend/tests/test_npc_memory.py).
- **Custom SSE-Over-POST Transport**: Hand-crafted a streaming Server-Sent Events parser over HTTP POST in [`frontend/src/api/client.js`](frontend/src/api/client.js) adhering to the W3C single-leading-space rule, handling `\r\n\r\n` boundary edge cases without corrupting whitespace.
- **Multi-Provider LLM Abstraction with Native Structured Outputs**: Implemented a unified `LLMClient` supporting Anthropic Claude, Google Gemini, and offline `MockLLMClient` with schema-enforced Pydantic output validation and environment-based provider precedence resolution in [`backend/tests/test_llm_client.py`](backend/tests/test_llm_client.py).
