import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app


@pytest.mark.asyncio
async def test_session_lifecycle_and_api_endpoints():
    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create a new session
        create_res = await client.post(
            "/api/sessions",
            json={"title": "The Northern Marches", "chapter": "Chapter 1: River of Ash"},
        )
        assert create_res.status_code == 201
        session_data = create_res.json()
        assert "id" in session_data
        session_id = session_data["id"]
        assert session_data["title"] == "The Northern Marches"
        assert session_data["current_node_id"] is not None

        # 2. Get initial state
        state_res = await client.get(f"/api/sessions/{session_id}/state")
        assert state_res.status_code == 200
        state = state_res.json()
        assert state["hp"] == 100
        assert state["mood"] == "Wary"
        assert len(state["npcs"]) >= 1
        assert state["npcs"][0]["relationship_label"] == "Neutral"

        # 3. Get initial story graph
        graph_res = await client.get(f"/api/sessions/{session_id}/graph")
        assert graph_res.status_code == 200
        graph = graph_res.json()
        assert len(graph["nodes"]) == 1
        root_node_id = graph["nodes"][0]["id"]
        assert graph["nodes"][0]["parent_id"] is None
        assert graph["nodes"][0]["turn_number"] == 0

        # 4. Get detail for opening root node
        node_res = await client.get(f"/api/sessions/{session_id}/nodes/{root_node_id}")
        assert node_res.status_code == 200
        node = node_res.json()
        assert "Rain lashes" in node["narration"]
        assert len(node["facts"]) >= 1

        # 5. Execute action with SSE streaming (Search keyword -> items_gained)
        action_res = await client.post(
            f"/api/sessions/{session_id}/action",
            json={"action_text": "Search the broken chariot by the gatehouse."},
        )
        assert action_res.status_code == 200
        assert "text/event-stream" in action_res.headers.get("content-type", "")

        # Parse SSE events from response body
        raw_sse = action_res.text
        lines = raw_sse.strip().split("\n")
        chunks = []
        done_event_data = None

        current_event = None
        for line in lines:
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                # SSE spec: strip single leading space after 'data:'
                data_val = line[6:]
                if current_event == "chunk":
                    chunks.append(data_val)
                elif current_event == "done":
                    done_event_data = json.loads(data_val)

        assert len(chunks) > 0, "Expected at least one 'event: chunk' in SSE response"
        assert done_event_data is not None, "Expected 'event: done' in SSE response"
        assert done_event_data["turn_number"] == 1
        assert done_event_data["parent_id"] == root_node_id
        assert len(done_event_data["state_delta"]["items_gained"]) >= 1

        # 6. Verify state reflects updated items and new current_node_id
        updated_state_res = await client.get(f"/api/sessions/{session_id}/state")
        assert updated_state_res.status_code == 200
        updated_state = updated_state_res.json()
        assert len(updated_state["inventory"]) >= 1
        assert updated_state["current_node_id"] == done_event_data["node_id"]

        # 7. Verify 404 on nonexistent session
        bad_action_res = await client.post(
            "/api/sessions/nonexistent-session-id/action",
            json={"action_text": "Test action"},
        )
        assert bad_action_res.status_code == 404

        bad_state_res = await client.get("/api/sessions/nonexistent-session-id/state")
        assert bad_state_res.status_code == 404
