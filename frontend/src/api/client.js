/**
 * Aetherfall API Client
 *
 * Handles HTTP requests and Server-Sent Events (SSE) streaming over POST
 * for the AI Dungeon Master backend.
 */

const BASE_URL = ''; // Relative URL leverages Vite's /api proxy to localhost:8000

/**
 * Initialize a new GameSession with starting world state and opening root StoryNode.
 * @param {Object} params
 * @param {string} [params.title]
 * @param {string} [params.chapter]
 * @returns {Promise<Object>} SessionCreateResponse
 */
export async function createSession({ title, chapter } = {}) {
  const res = await fetch(`${BASE_URL}/api/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title || 'The Sunken Reach',
      chapter: chapter || 'Chapter 1: The Drowned Road',
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create session (${res.status})`);
  }

  return res.json();
}

/**
 * Fetch denormalized session state (HP, focus, mood, location, inventory, quests, NPCs).
 * @param {string} sessionId
 * @returns {Promise<Object>} SessionStateResponse
 */
export async function getSessionState(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/state`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch session state (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch complete story graph with all nodes and computed statuses (current/path/alternate/abandoned).
 * @param {string} sessionId
 * @returns {Promise<Object>} StoryGraphResponse
 */
export async function getStoryGraph(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/graph`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch story graph (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch detailed StoryNode inspection (narration, action, facts, status).
 * @param {string} sessionId
 * @param {string} nodeId
 * @returns {Promise<Object>} StoryNodeDetailResponse
 */
export async function getStoryNodeDetail(sessionId, nodeId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/nodes/${nodeId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch node detail (${res.status})`);
  }
  return res.json();
}

/**
 * Stream a player turn action via SSE over POST.
 *
 * NOTE: The native browser `EventSource` API ONLY supports GET with no body.
 * Because the action endpoint requires a POST body with action_text and optional from_node_id,
 * this function reads `response.body.getReader()` directly and parses the SSE stream manually.
 *
 * CRITICAL SSE SPEC REQUIREMENT:
 * Parsers strip exactly ONE leading space character following the 'data:' prefix.
 * We do NOT call `.trim()` on the data payload, preserving intentional paragraph indentations
 * and whitespace in narrative prose.
 *
 * @param {string} sessionId
 * @param {Object} options
 * @param {string} options.actionText - The player's proposed action
 * @param {string|null} [options.fromNodeId] - Optional ancestor node ID to fork a branch
 * @param {Function} [options.onChunk] - Callback for narrative text chunk: onChunk(chunkText)
 * @param {Function} [options.onDone] - Callback when turn is complete: onDone(turnResult)
 * @param {Function} [options.onError] - Callback on stream or HTTP error: onError(error)
 */
export async function streamTurnAction(sessionId, {
  actionText,
  fromNodeId = null,
  onChunk,
  onDone,
  onError,
}) {
  try {
    const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/action`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify({
        action_text: actionText,
        from_node_id: fromNodeId || null,
      }),
    });

    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      const error = new Error(errJson.detail || `Action request failed (${res.status})`);
      error.status = res.status;
      error.detail = errJson.detail;
      if (onError) onError(error);
      throw error;
    }

    if (!res.body) {
      throw new Error('ReadableStream not supported on response body');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const processEventBlock = (block) => {
      if (!block.trim()) return;
      const lines = block.split(/\r?\n/);
      let eventType = 'message';
      const dataLines = [];

      for (const rawLine of lines) {
        const line = rawLine.replace(/\r$/, '');
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          // SSE Specification: Strip ONLY the single leading space after 'data:'
          let dataContent = line.slice(5);
          if (dataContent.startsWith(' ')) {
            dataContent = dataContent.slice(1);
          }
          dataLines.push(dataContent);
        }
      }

      const fullData = dataLines.join('\n');

      if (eventType === 'chunk') {
        if (onChunk) onChunk(fullData);
      } else if (eventType === 'done') {
        try {
          const parsed = JSON.parse(fullData);
          if (onDone) onDone(parsed);
        } catch (e) {
          console.error('Failed to parse SSE done event payload:', e, fullData);
          if (onError) onError(e);
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Scan and extract all complete event blocks delimited by CRLF CRLF (\r\n\r\n) or LF LF (\n\n)
      let boundaryIndex;
      while ((boundaryIndex = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const isCrlf = buffer.substr(boundaryIndex, 4) === '\r\n\r\n';
        const delimiterLength = isCrlf ? 4 : 2;
        const block = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + delimiterLength);
        processEventBlock(block);
      }
    }

    // Process any remaining event left in buffer on stream completion
    if (buffer.trim()) {
      processEventBlock(buffer);
      buffer = '';
    }
  } catch (err) {
    console.error('[SSE Action Stream Error]:', err);
    if (onError) onError(err);
    throw err;
  }
}

/**
 * Fetch all four canonical chapter definitions and objectives.
 * @returns {Promise<Array<{number: number, title: string, objective: string, completion_quest_title: string, next_chapter_number: number|null}>>}
 */
export async function getChapters() {
  const res = await fetch(`${BASE_URL}/api/chapters`);
  if (!res.ok) {
    throw new Error(`Failed to fetch chapters (${res.status})`);
  }
  return res.json();
}

/**
 * Fetch the world map derived from the player's active travel path.
 * @param {string} sessionId
 * @returns {Promise<{session_id: string, current_location: string, nodes: Array, edges: Array}>} WorldMapResponse
 */
export async function getWorldMap(sessionId) {
  const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/map`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to fetch world map (${res.status})`);
  }
  return res.json();
}
