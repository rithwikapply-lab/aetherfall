# Aetherfall

> **An AI Dungeon Master engine where the world is a relational database, not a chat transcript.**

Aetherfall is an interactive dark-fantasy narrative engine built with **FastAPI**, **SQLAlchemy 2.0 (Async ORM)**, and **React**. Rather than appending player prompts and responses into an ever-expanding conversational context window, Aetherfall models game state as discrete database entities (`GameSession`, `StoryNode`, `InventoryItem`, `Quest`, `NPC`, and `NPCMemoryEntry`). 

Turns form an explicit, directed tree of `StoryNode` records linked by self-referential `parent_id` foreign keys. This architectural foundation makes branching timelines, canon continuity enforcement, and explainable NPC memory retrieval possible—capabilities that cannot be achieved with single-prompt chatbot wrappers.

---

## 1. Why A Relational Database Over Chat Transcripts?

Most LLM-based interactive fiction systems are implemented as "chat wrappers": every turn appends the player's prompt and the model's response to an ongoing string history passed into the next generation. This approach inevitably fails for three structural reasons:

1. **Context Window Degradation & Token Costs**: History length grows quadratically with turn count, quickly hitting model context limits, ballooning latency, and increasing inference costs.
2. **Context Drift & Hallucinations**: World facts established 20 turns prior become diluted among thousands of tokens. The model forgets inventory items, revives deceased characters, or contradicts canon because facts are merely unindexed tokens in a prompt string.
3. **Impossibility of Branching**: In a flat transcript, exploring an alternative choice requires destructively truncating history. You cannot maintain simultaneous alternate branches or rewind to an earlier fork point without corrupting the timeline.

In Aetherfall, **world state is a database**:
- **Branching is a Tree**: Each turn creates a `StoryNode` with a `parent_id`. Replaying from an earlier turn forks a sibling node under that ancestor, preserving superseded branches in the database.
- **State is Atomic**: HP, Focus, inventory mutations, and NPC sentiments are extracted via structured tool calling into a Pydantic `StateDelta` and committed atomically.
- **Canon is Enforced**: A dedicated Continuity Guard queries immutable ancestor facts along the active branch to detect and prevent narrative contradictions before committing.
- **Memory is Queryable**: NPCs maintain discrete memory logs scored by lexical overlap, recency, and salience, rather than relying on the LLM to recall details from prompt history.

---

## 2. Quickstart

Aetherfall is designed to run **100% offline with zero external dependencies and zero API keys** using `MockLLMClient` and SQLite, while providing production-ready support for PostgreSQL, Redis, and live LLM generation with either Anthropic Claude or Google Gemini (via free Google AI Studio keys).

### Option A: Local Dev Mode (Zero Dependencies, Offline Mock Mode)

#### 1. Backend (FastAPI + SQLite)
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### 2. Frontend (React + Vite)
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). You can immediately create a campaign, submit actions, stream prose, inspect the story graph, and fork branches without needing any API key or network access.

---

### Option B: Docker Compose (PostgreSQL 16 + Redis 7 + API Container)

To run the containerized production-like stack:

```bash
# Optional: Export an API key to enable live narrative generations.
# Option 1: Google Gemini (Free tier available on Google AI Studio)
export GOOGLE_API_KEY="your-gemini-api-key"
export GEMINI_MODEL="gemini-2.5-flash"

# Option 2: Anthropic Claude (Takes precedence if both are set)
# export ANTHROPIC_API_KEY="your-anthropic-api-key"
# export LLM_MODEL="claude-sonnet-4-5"

# If both are omitted or empty, the engine automatically defaults to MockLLMClient.
docker compose up --build
```

The `api` container waits for PostgreSQL's `healthcheck` (`pg_isready`) before launching, exposes port `8000`, and runs uvicorn against `postgresql+asyncpg://`.

---

## 3. Architecture & Four-Agent Turn Pipeline

Every player turn executes through an orchestrated four-agent pipeline:

```
                  Player Action
                        │
                        ▼
       ┌─────────────────────────────────┐
       │     1. NPC Memory Agent         │
       │  (Lexical Jaccard + Recency)    │
       └────────────────┬────────────────┘
                        │ Injects relevant memory
                        ▼
       ┌─────────────────────────────────┐
       │       2. Narrator Agent         │
       │ (SSE Streaming Prose Generation)│
       └────────────────┬────────────────┘
                        │ Complete narrative prose
                        ▼
       ┌─────────────────────────────────┐
       │   3. State-Extraction Agent     │
       │ (Structured StateDelta Tooling) │
       └────────────────┬────────────────┘
                        │ Atomically commits to DB
                        ▼
       ┌─────────────────────────────────┐
       │    4. Continuity Guard Agent    │
       │ (Tier 1 Bypass / Tier 2 Verify) │
       └────────────────┬────────────────┘
                        │
                        ▼
                   Story Graph
          (Branch node & statuses updated)
```

### Turn Execution Steps

1. **NPC Memory Agent** ([`backend/app/agents/npc_memory.py`](file:///Users/rithwikdevireddy/backend/app/agents/npc_memory.py)):
   Inspects all NPCs present in the scene. Scores their memory entries against the player's action using tokenized Jaccard similarity, normalized salience, and recency decay. If the highest score clears the threshold (default: 0.25), the recalled memory is injected into the Narrator's prompt.
2. **Narrator Agent** ([`backend/app/agents/narrator.py`](file:///Users/rithwikdevireddy/backend/app/agents/narrator.py)):
   Generates rich narrative prose chunk-by-chunk. Streamed live to the browser via Server-Sent Events (SSE) over `POST /api/sessions/{id}/action`.
3. **State-Extraction Agent** ([`backend/app/agents/state_extractor.py`](file:///Users/rithwikdevireddy/backend/app/agents/state_extractor.py)):
   Analyzes the completed narration against the player's action using forced structured output (`StateDelta` schema). Atomically applies state mutations in SQLAlchemy:
   - Updates player HP, focus, mood, and location on `GameSession`.
   - Adds newly acquired `InventoryItem` records or marks dropped items.
   - Adjusts NPC affinity scores and appends new `NPCMemoryEntry` records.
   - Appends new canon facts to the new `StoryNode`.
4. **Continuity Guard Agent** ([`backend/app/agents/continuity_guard.py`](file:///Users/rithwikdevireddy/backend/app/agents/continuity_guard.py)):
   Traverses the parent chain from the new node back to the root to collect all established canon facts for this branch. Evaluates the narration using a **two-tier architecture**:
   - **Tier 1 (Short-Circuit)**: If zero ancestor facts exist (common on opening turns), bypasses the LLM entirely and returns `has_contradiction=False` with zero latency.
   - **Tier 2 (Structured Verification)**: If canon facts exist, runs a structured schema check (`ContinuityResult`) to detect direct contradictions, returning the violating claim, the violated fact, and the reasoning.

---

### The Branching Mechanism (`parent_id` / `from_node_id`)

The story graph is an explicit tree where every node points to its ancestor:

```
[Root: Turn 0]
      │
[Node 1: Turn 1 (Courtyard)]
      ├───► [Node 2: Turn 2 (Crypts)] ───► [Node 3: Turn 3 (Gargoyle)] (Abandoned)
      │
      └───► [Node 4: Turn 2 (Hidden Alcove)] (Current Leaf)
```

1. **Standard Turn**: When continuing from the active leaf, `target_parent_id = session.current_node_id`. The new node is parented to the current leaf.
2. **Replay Turn**: In the Story Graph UI, clicking any ancestor node and selecting **"Replay from here"** sends `POST /api/sessions/{id}/action` with `from_node_id = <ancestor_id>`.
3. **Tree Forking**: The pipeline sets `parent_id = from_node_id`, creates a new child under that ancestor, and updates `session.current_node_id` to point at the new branch.
4. **Dynamic Node Status Classification**: The backend walks the tree to classify every node:
   - `current`: The active leaf node (`session.current_node_id`).
   - `path`: Ancestor nodes on the direct line between root and `current`.
   - `alternate`: Direct siblings at fork points off the active path.
   - `abandoned`: Deeper descendants of superseded, inactive branches.

---

## 4. Why Lexical Memory Over Vector Embeddings?

The NPC Memory Agent uses pure-Python lexical scoring (Jaccard similarity on non-stopword tokens + normalized salience + recency decay) rather than a vector database or embedding service.

This is a **deliberate architectural decision**, not a shortcut:

1. **Deterministic Explainability**: Neural embeddings produce opaque cosine similarity floats that cannot explain *why* a memory was triggered. In Aetherfall, memory recall is completely explainable: you can audit the literal token overlap between `"river bridge rations"` in the action and the NPC's memory record.
2. **Zero External Dependencies**: Running a vector database requires embedding APIs, network latency, or local embedding models (e.g. sentence-transformers). Pure lexical scoring runs entirely offline with zero dependencies, executing in sub-millisecond time.
3. **Comprehensive Unit Testing**: Pure lexical scoring allows the entire memory retrieval, thresholding, and recency decay pipeline to be tested in standard unit tests without spinning up vector stores or mocking embedding calls.
4. **Clean Swap Boundary**: The module exposes high-level functions (`retrieve_relevant` and `best_recall`). If semantic embedding search is desired in the future, only the internal `score_memory` function needs modification—the four-agent pipeline and calling code remain completely unchanged.

---

## 5. Automated Test Suite & Architecture Proofs

The backend includes a comprehensive 38-test suite in [`backend/tests/`](file:///Users/rithwikdevireddy/backend/tests/) running via `pytest` and `pytest-asyncio`. Every test runs with **zero network calls and zero API keys** against `MockLLMClient` and ephemeral per-test SQLite databases.

```bash
cd backend
.venv/bin/pytest -v
============================== 38 passed in 0.98s ==============================
```

### Key Architectural Proofs

- **Proof of Branching Replay (`test_replay_from_earlier_node_creates_a_branch` in `test_pipeline.py`)**:
  Seeds a session with 3 sequential turns: `root` &rarr; `node1` &rarr; `node2` &rarr; `node3` with active leaf at `node3`. Replays from `node1.id`. Asserts:
  1. The new node's `parent_id` is `node1.id`, **not** `node3.id`.
  2. `node3`'s narration, facts, and parent chain remain 100% untouched.
  3. `session.current_node_id` now points to the new branch node.
  4. `node1` now has exactly two distinct children.
  
  > **Deliberate-Break Validation**: During Phase 5 verification, we intentionally hardcoded the pipeline to ignore `from_node_id` (`target_parent_id = session.current_node_id`). Running this test immediately failed with:
  > `AssertionError: Expected new branch node parent to be node1 (...), but got (...)`
  > Reverting the break restored a clean pass, proving the test actively catches regressions rather than passing vacuously.

- **Proof of Tier-1 Continuity Short-Circuit (`test_continuity_guard_tier1_short_circuit` in `test_continuity_guard.py`)**:
  Passes an `ExplosiveLLMClient` that raises an exception if any method is called. Verifies that when a story branch contains 0 ancestor facts, the Continuity Guard completes with `has_contradiction=False` and `"Tier 1 short-circuit"` without touching the LLM.

- **Proof of Abandoned Status Classification (`test_story_graph_abandoned_branch_status` in `test_api_game_flow.py`)**:
  Builds a 4-turn chain, forks from turn 1, and confirms via `GET /api/sessions/{id}/graph` that the new leaf is `current`, ancestors are `path`, the direct sibling is `alternate`, and deep superseded nodes are classified as `abandoned`.

---

## 6. Known Limitations & Trade-offs

In the spirit of honest engineering documentation:

1. **MockLLMClient Narration is Deterministic**: `MockLLMClient` generates templated, deterministic prose derived from action hashes and keywords. It proves that the async generators, SSE stream, and delta extraction work cleanly, but lacks the creative richness of a live model. Live, dynamic storytelling requires an `ANTHROPIC_API_KEY` or `GOOGLE_API_KEY`.
2. **Redis is Provisioned But Unwired**: Redis 7 is included in `docker-compose.yml` to demonstrate multi-container orchestration, but session caching and pub/sub message queuing have not yet been wired into the FastAPI backend (state currently resides directly in PostgreSQL/SQLite).
3. **No Per-Turn AI Scene Art**: While location names and mood tags are tracked, dynamic image generation (e.g. Stable Diffusion or Imagen) for every turn is not implemented.
4. **Story Graph Layout Scale**: The SVG tree layout positions nodes cleanly along the depth and branch axes for demo campaigns (tens of nodes). It is not optimized for massive trees with hundreds of concurrent branches, which would require a force-directed or virtualized layout engine.
5. **No Authentication or Multi-Tenant Scoping**: Sessions are partitioned by UUID, but there is no user authentication, login flow, or row-level access control.
6. **Frontend Lacks Automated Unit Tests**: The React frontend was verified manually against the live backend rather than through automated component test suites (e.g. Cypress or Vitest).
7. **The CRLF SSE Parser Bug**: During manual playtesting, a real bug was discovered where `buffer.split('\n\n')` failed on Windows/HTTP-standard `\r\n\r\n` line endings from uvicorn, causing chunks to accumulate and fail with `Unexpected token 'E' in JSON`. The automated tests with `httpx` missed this because `httpx` normalized line breaks. The bug was resolved by updating the client to scan for `/\r?\n\r?\n/` boundaries. This serves as a reminder that automated API unit tests can miss real client-side transport quirks.

---

## 7. Portfolio & Interview Highlights

- **Branching Directed Graph Architecture**: Engineered a branching game state engine in SQLAlchemy 2.0 async ORM where game turns form an immutable directed tree; proved timeline forking via `test_replay_from_earlier_node_creates_a_branch` in [`backend/tests/test_pipeline.py`](file:///Users/rithwikdevireddy/backend/tests/test_pipeline.py).
- **Two-Tier LLM Continuity Guard**: Built a cost- and latency-optimized verification agent that short-circuits LLM calls on opening turns; proved zero LLM invocation with an explosive mock in [`backend/tests/test_continuity_guard.py`](file:///Users/rithwikdevireddy/backend/tests/test_continuity_guard.py).
- **Custom SSE-Over-POST Transport**: Hand-crafted a streaming Server-Sent Events parser over HTTP POST in [`frontend/src/api/client.js`](file:///Users/rithwikdevireddy/frontend/src/api/client.js) adhering to the W3C single-leading-space rule to stream narrative prose without corrupting whitespace.
- **Explainable Lexical Memory Scoring**: Designed a pure-Python NPC memory retrieval system combining tokenized Jaccard overlap, salience normalization, and recency decay; thoroughly verified without external vector database dependencies in [`backend/tests/test_npc_memory.py`](file:///Users/rithwikdevireddy/backend/tests/test_npc_memory.py).
- **Multi-Provider LLM Client Abstraction**: Encapsulated streaming text and native schema-enforced structured generation behind an abstract `LLMClient` interface with automatic runtime fallback (Anthropic $\to$ Gemini $\to$ Mock), tested without live API credits in [`backend/tests/test_llm_client.py`](file:///Users/rithwikdevireddy/backend/tests/test_llm_client.py).
