import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import async_session_maker
from app.main import app
from app.models import GameSession, StoryNode


@pytest.fixture
async def api_client():
    """Async HTTP client connected to the FastAPI ASGI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_create_session(api_client: AsyncClient):
    """Verify POST /api/sessions initializes a game session and opening root node."""
    res = await api_client.post(
        "/api/sessions",
        json={"title": "The Northern Marches", "chapter": "Chapter 1: The Drowned Road"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["title"] == "The Northern Marches"
    assert data["chapter"] == "Chapter 1: The Drowned Road"
    assert data["chapter_number"] == 1
    assert data["completed_chapters"] == []
    assert data["current_node_id"] is not None


@pytest.mark.asyncio
async def test_get_session_state_initial(api_client: AsyncClient):
    """Verify GET /api/sessions/{id}/state returns denormalized state, quests, and NPCs."""
    # 1. Create session
    create_res = await api_client.post(
        "/api/sessions",
        json={"title": "State Check Campaign"},
    )
    session_id = create_res.json()["id"]

    # 2. Get initial state
    res = await api_client.get(f"/api/sessions/{session_id}/state")
    assert res.status_code == 200
    state = res.json()
    assert state["id"] == session_id
    assert state["hp"] == 100
    assert state["focus"] == 50
    assert state["location"] == "The Sunken Crossroads"
    assert state["mood"] == "Wary"
    assert state["inventory"] == []
    assert len(state["quests"]) == 1
    assert state["quests"][0]["status"] == "active"
    assert len(state["npcs"]) >= 1
    assert state["npcs"][0]["name"] == "Kael"
    assert state["npcs"][0]["relationship_label"] == "Neutral"


@pytest.mark.asyncio
async def test_take_action_via_sse_streaming(api_client: AsyncClient):
    """Verify POST /api/sessions/{id}/action streams prose chunks and emits final done TurnResult."""
    # 1. Create session
    create_res = await api_client.post("/api/sessions", json={"title": "SSE Stream Test"})
    session_id = create_res.json()["id"]
    root_node_id = create_res.json()["current_node_id"]

    # 2. Post action (Search keyword -> items_gained)
    res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={"action_text": "Search the broken cargo wagon for salvageable gear."},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")

    # 3. Consume the SSE event stream
    chunks = []
    done_event_data = None
    current_event = None

    for line in res.text.strip().split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            # SSE spec: strip single leading space after 'data:'
            data_val = line[6:]
            if current_event == "chunk":
                chunks.append(data_val)
            elif current_event == "done":
                done_event_data = json.loads(data_val)

    # Assertions on consumed stream
    assert len(chunks) > 0, "Expected at least one narrative chunk event in SSE stream"
    full_narration = "".join(chunks).strip()
    assert len(full_narration) > 0

    assert done_event_data is not None, "Expected 'event: done' in SSE stream"
    assert done_event_data["session_id"] == session_id
    assert done_event_data["turn_number"] == 1
    assert done_event_data["parent_id"] == root_node_id
    assert done_event_data["node_id"] is not None
    assert len(done_event_data["state_delta"]["items_gained"]) >= 1
    assert done_event_data["continuity"]["has_contradiction"] is False


@pytest.mark.asyncio
async def test_state_updates_after_turn_action(api_client: AsyncClient):
    """Verify GET /api/sessions/{id}/state reflects changes committed during an action."""
    create_res = await api_client.post("/api/sessions", json={"title": "State Update Test"})
    session_id = create_res.json()["id"]

    # Take search action
    action_res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={"action_text": "Search the mossy stone alcove for tools."},
    )
    assert action_res.status_code == 200

    done_data = None
    current_event = None
    for line in action_res.text.strip().split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: ") and current_event == "done":
            done_data = json.loads(line[6:])

    assert done_data is not None
    new_node_id = done_data["node_id"]

    # Check updated session state
    state_res = await api_client.get(f"/api/sessions/{session_id}/state")
    assert state_res.status_code == 200
    state = state_res.json()
    assert state["current_node_id"] == new_node_id
    assert len(state["inventory"]) >= 1
    assert state["inventory"][0]["name"] == done_data["state_delta"]["items_gained"][0]["name"]


@pytest.mark.asyncio
async def test_story_graph_node_statuses_and_branching(api_client: AsyncClient):
    """Verify GET /api/sessions/{id}/graph returns correct status for current/path/alternate."""
    # 1. Create session -> 1 node (root), status='current'
    create_res = await api_client.post("/api/sessions", json={"title": "Graph Status Test"})
    session_id = create_res.json()["id"]
    root_node_id = create_res.json()["current_node_id"]

    graph_res = await api_client.get(f"/api/sessions/{session_id}/graph")
    assert graph_res.status_code == 200
    graph = graph_res.json()
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["id"] == root_node_id
    assert graph["nodes"][0]["status"] == "current"

    # 2. Linear turn 1 action -> root becomes 'path', turn 1 becomes 'current'
    turn1_res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={"action_text": "Search the broken cart."},
    )
    assert turn1_res.status_code == 200
    turn1_data = None
    for line in turn1_res.text.strip().split("\n"):
        if line.startswith("data: ") and turn1_data is None:
            try:
                turn1_data = json.loads(line[6:])
            except Exception:
                pass
    assert turn1_data is not None
    turn1_node_id = turn1_data["node_id"]

    graph_res2 = await api_client.get(f"/api/sessions/{session_id}/graph")
    graph2 = graph_res2.json()
    node_map = {n["id"]: n for n in graph2["nodes"]}
    assert node_map[root_node_id]["status"] == "path"
    assert node_map[turn1_node_id]["status"] == "current"

    # 3. Branching replay from root_node_id
    # Root remains 'path', new fork becomes 'current', previous turn1 becomes 'alternate'
    fork_res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={
            "action_text": "Ask Kael about another way across the flooded marsh.",
            "from_node_id": root_node_id,
        },
    )
    assert fork_res.status_code == 200
    fork_data = None
    for line in fork_res.text.strip().split("\n"):
        if line.startswith("data: ") and fork_data is None:
            try:
                fork_data = json.loads(line[6:])
            except Exception:
                pass
    assert fork_data is not None
    fork_node_id = fork_data["node_id"]
    assert fork_node_id != turn1_node_id

    # Verify graph statuses after branching replay
    graph_res3 = await api_client.get(f"/api/sessions/{session_id}/graph")
    graph3 = graph_res3.json()
    assert len(graph3["nodes"]) == 3
    node_map3 = {n["id"]: n for n in graph3["nodes"]}
    assert node_map3[root_node_id]["status"] == "path"
    assert node_map3[fork_node_id]["status"] == "current"
    assert node_map3[turn1_node_id]["status"] == "alternate"


@pytest.mark.asyncio
async def test_get_story_node_detail(api_client: AsyncClient):
    """Verify GET /api/sessions/{id}/nodes/{node_id} returns single node details."""
    create_res = await api_client.post("/api/sessions", json={"title": "Detail Test"})
    session_id = create_res.json()["id"]
    root_node_id = create_res.json()["current_node_id"]

    res = await api_client.get(f"/api/sessions/{session_id}/nodes/{root_node_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == root_node_id
    assert detail["session_id"] == session_id
    assert "Rain lashes" in detail["narration"]
    assert len(detail["facts"]) >= 1
    assert detail["status"] == "current"


@pytest.mark.asyncio
async def test_unknown_session_id_returns_clean_404(api_client: AsyncClient):
    """Verify accessing nonexistent session IDs returns clean 404 instead of 500."""
    fake_id = "nonexistent-session-uuid-0000"

    state_res = await api_client.get(f"/api/sessions/{fake_id}/state")
    assert state_res.status_code == 404
    assert "not found" in state_res.json()["detail"].lower()

    graph_res = await api_client.get(f"/api/sessions/{fake_id}/graph")
    assert graph_res.status_code == 404
    assert "not found" in graph_res.json()["detail"].lower()

    node_res = await api_client.get(f"/api/sessions/{fake_id}/nodes/some-node")
    assert node_res.status_code == 404
    assert "not found" in node_res.json()["detail"].lower()

    action_res = await api_client.post(
        f"/api/sessions/{fake_id}/action",
        json={"action_text": "Do something in a ghost session."},
    )
    assert action_res.status_code == 404
    assert "not found" in action_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_action_with_invalid_from_node_id_returns_clean_404(api_client: AsyncClient):
    """Verify replaying from an invalid/unrelated node_id returns a clean 404."""
    create_res = await api_client.post("/api/sessions", json={"title": "Invalid Node Test"})
    session_id = create_res.json()["id"]

    res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={
            "action_text": "Replay from non-existent node.",
            "from_node_id": "nonexistent-node-id-9999",
        },
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_story_graph_abandoned_branch_status(api_client: AsyncClient):
    """Verify deeper superseded branch nodes receive status='abandoned'.

    Scenario:
        root (turn 0) -> node1 (turn 1) -> node2 (turn 2) -> node3 (turn 3) -> node4 (turn 4)
    with current_node_id pointing at node4.

    Replay from node1 creates:
        node1 -> fork_node (new current leaf)

    Expected graph statuses:
    - fork_node: 'current'
    - root, node1: 'path' (ancestors of active leaf)
    - node2: 'alternate' (direct child of active ancestor node1)
    - node3, node4: 'abandoned' (deeper descendants of superseded branch)
    """
    async with async_session_maker() as session:
        game_session = GameSession(
            title="Abandoned Branch Campaign",
            chapter="Chapter 1: The Descent",
            hp=100,
            max_hp=100,
            focus=50,
            max_focus=50,
            location="The Ancient Crypts",
            mood="Grim",
        )
        session.add(game_session)
        await session.flush()

        root_node = StoryNode(
            session_id=game_session.id,
            parent_id=None,
            turn_number=0,
            narration="Opening root node at the crossroads.",
            facts=["the bridge is out"],
        )
        session.add(root_node)
        await session.flush()

        node1 = StoryNode(
            session_id=game_session.id,
            parent_id=root_node.id,
            turn_number=1,
            player_action="Action 1",
            narration="Turn 1 narration",
            facts=[],
        )
        session.add(node1)
        await session.flush()

        node2 = StoryNode(
            session_id=game_session.id,
            parent_id=node1.id,
            turn_number=2,
            player_action="Action 2",
            narration="Turn 2 narration",
            facts=[],
        )
        session.add(node2)
        await session.flush()

        node3 = StoryNode(
            session_id=game_session.id,
            parent_id=node2.id,
            turn_number=3,
            player_action="Action 3",
            narration="Turn 3 narration",
            facts=[],
        )
        session.add(node3)
        await session.flush()

        node4 = StoryNode(
            session_id=game_session.id,
            parent_id=node3.id,
            turn_number=4,
            player_action="Action 4",
            narration="Turn 4 narration",
            facts=[],
        )
        session.add(node4)
        await session.flush()

        # Point session at leaf node4
        game_session.current_node_id = node4.id
        await session.commit()

        session_id = game_session.id
        root_id = root_node.id
        node1_id = node1.id
        node2_id = node2.id
        node3_id = node3.id
        node4_id = node4.id

    # Replay from node1 via API action endpoint
    fork_res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={
            "action_text": "Search the western alcove instead.",
            "from_node_id": node1_id,
        },
    )
    assert fork_res.status_code == 200

    fork_data = None
    for line in fork_res.text.strip().split("\n"):
        if line.startswith("data: ") and fork_data is None:
            try:
                fork_data = json.loads(line[6:])
            except Exception:
                pass
    assert fork_data is not None
    fork_node_id = fork_data["node_id"]
    assert fork_data["parent_id"] == node1_id

    # Query the story graph
    graph_res = await api_client.get(f"/api/sessions/{session_id}/graph")
    assert graph_res.status_code == 200
    graph = graph_res.json()
    assert len(graph["nodes"]) == 6

    node_map = {n["id"]: n for n in graph["nodes"]}

    # Specific status assertions:
    assert node_map[fork_node_id]["status"] == "current"
    assert node_map[root_id]["status"] == "path"
    assert node_map[node1_id]["status"] == "path"
    assert node_map[node2_id]["status"] == "alternate"
    assert node_map[node3_id]["status"] == "abandoned"
    assert node_map[node4_id]["status"] == "abandoned"


@pytest.mark.asyncio
async def test_api_action_rejected_on_game_over_session(api_client: AsyncClient):
    """Verify API returns 400 when an action is submitted for an already-ended session."""
    # 1. Create a session
    create_res = await api_client.post("/api/sessions", json={"title": "Terminal API Campaign"})
    assert create_res.status_code == 201
    session_id = create_res.json()["id"]

    # 2. Directly set session to game over in the DB
    async with async_session_maker() as db:
        session = await db.get(GameSession, session_id)
        session.hp = 0
        session.is_game_over = True
        session.game_over_reason = "death"
        session.game_over_summary = "Fell to mortal wounds."
        await db.commit()

    # 3. Verify GET /api/sessions/{id}/state exposes game_over details
    state_res = await api_client.get(f"/api/sessions/{session_id}/state")
    assert state_res.status_code == 200
    state_data = state_res.json()
    assert state_data["is_game_over"] is True
    assert state_data["game_over_reason"] == "death"
    assert state_data["game_over_summary"] == "Fell to mortal wounds."

    # 4. Attempt action on the game over session -> expect HTTP 400 Bad Request
    action_res = await api_client.post(
        f"/api/sessions/{session_id}/action",
        json={"action_text": "Crawl toward the ancient gate."},
    )
    assert action_res.status_code == 400
    assert "already ended" in action_res.json()["detail"].lower()

