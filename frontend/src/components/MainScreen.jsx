import React, { useState, useEffect, useRef } from 'react';
import {
  getSessionState,
  getStoryNodeDetail,
  streamTurnAction,
} from '../api/client';

export default function MainScreen({
  session,
  onNavigateToGraph,
  onNewCampaign,
  pendingReplay, // { fromNodeId, defaultActionText } if returning from Graph screen
  onClearPendingReplay,
}) {
  const [sessionState, setSessionState] = useState(null);
  const [storyTurns, setStoryTurns] = useState([]);
  const [currentStreamingText, setCurrentStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [actionInput, setActionInput] = useState('');
  const [activeReplayNodeId, setActiveReplayNodeId] = useState(null);
  const [lastTurnResult, setLastTurnResult] = useState(null);
  const [error, setError] = useState(null);

  const narrativeEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll narration container on new text
  const scrollToBottom = () => {
    narrativeEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [storyTurns, currentStreamingText]);

  // Initial load: Fetch state and root opening StoryNode
  useEffect(() => {
    if (!session?.id) return;

    let isMounted = true;

    async function loadInitialScene() {
      try {
        const state = await getSessionState(session.id);
        if (!isMounted) return;
        setSessionState(state);

        if (state.current_node_id) {
          const rootNode = await getStoryNodeDetail(session.id, state.current_node_id);
          if (!isMounted) return;

          setStoryTurns([
            {
              turn_number: rootNode.turn_number,
              player_action: null,
              narration: rootNode.narration,
              location: rootNode.location,
              facts: rootNode.facts,
            },
          ]);
        }
      } catch (err) {
        if (isMounted) setError(err.message);
      }
    }

    loadInitialScene();

    return () => {
      isMounted = false;
    };
  }, [session?.id]);

  // Check if we came from Graph screen with a pending replay fork
  useEffect(() => {
    if (pendingReplay?.fromNodeId) {
      setActiveReplayNodeId(pendingReplay.fromNodeId);
      if (pendingReplay.defaultActionText) {
        setActionInput(pendingReplay.defaultActionText);
      }
      onClearPendingReplay?.();
    }
  }, [pendingReplay, onClearPendingReplay]);

  // Execute player action via SSE streaming
  const handleActionSubmit = async (e) => {
    e?.preventDefault();
    const trimmedAction = actionInput.trim();
    if (!trimmedAction || isStreaming) return;

    setError(null);
    setIsStreaming(true);
    setCurrentStreamingText('');
    const targetNodeId = activeReplayNodeId;
    setActiveReplayNodeId(null); // Reset replay target after submit

    // Optimistically record the player's proposed action
    const currentActionText = trimmedAction;
    setActionInput('');

    try {
      await streamTurnAction(session.id, {
        actionText: currentActionText,
        fromNodeId: targetNodeId,
        onChunk: (chunk) => {
          setCurrentStreamingText((prev) => prev + chunk);
        },
        onDone: async (turnResult) => {
          setLastTurnResult(turnResult);
          setCurrentStreamingText('');
          setIsStreaming(false);

          // Append completed turn to history
          setStoryTurns((prev) => [
            ...prev,
            {
              turn_number: turnResult.turn_number,
              player_action: currentActionText,
              narration: turnResult.narration,
              location: turnResult.location,
              state_delta: turnResult.state_delta,
              recalled_memory: turnResult.recalled_memory,
              continuity: turnResult.continuity,
            },
          ]);

          // Refresh full denormalized world state (inventory, quests, NPCs, stats)
          try {
            const updatedState = await getSessionState(session.id);
            setSessionState(updatedState);
          } catch (e) {
            console.error('Failed to reload state after turn:', e);
          }
        },
        onError: (err) => {
          setError(err.message || 'Stream connection interrupted.');
          setIsStreaming(false);
        },
      });
    } catch (err) {
      setError(err.message || 'Action failed to execute.');
      setIsStreaming(false);
    }
  };

  const hpPercent = sessionState
    ? Math.max(0, Math.min(100, Math.round((sessionState.hp / sessionState.max_hp) * 100)))
    : 100;
  const focusPercent = sessionState
    ? Math.max(0, Math.min(100, Math.round((sessionState.focus / sessionState.max_focus) * 100)))
    : 100;

  return (
    <div className="main-layout">
      {/* Top Header Navigation Bar */}
      <header className="main-navbar">
        <div className="navbar-brand">
          <span className="brand-logo">⚔ AETHERFALL</span>
          <span className="brand-title">{sessionState?.title || session?.title}</span>
          <span className="chapter-pill">{sessionState?.chapter || session?.chapter}</span>
        </div>

        <div className="navbar-actions">
          {activeReplayNodeId && (
            <div className="replay-indicator">
              <span>Branching from node: <code>{activeReplayNodeId.slice(0, 8)}...</code></span>
              <button
                type="button"
                className="btn-text-cancel"
                onClick={() => setActiveReplayNodeId(null)}
              >
                ✕ Cancel Replay
              </button>
            </div>
          )}
          <button
            type="button"
            className="btn-graph-nav"
            onClick={onNavigateToGraph}
            title="Open Interactive Story Graph"
          >
            <span className="nav-icon">🌿</span> Story Graph
          </button>
          <button
            type="button"
            className="btn-new-nav"
            onClick={onNewCampaign}
            title="Start New Campaign"
          >
            New Campaign
          </button>
        </div>
      </header>

      {/* Main Content Area: Left Narrative & Action, Right World Panels */}
      <div className="main-body">
        {/* Left Column: Vitals, Narrative Stream, Action Input */}
        <div className="narrative-column">
          {/* Status & Vitals Bar */}
          <div className="vitals-bar">
            <div className="vital-item location-vital">
              <span className="vital-icon">📍</span>
              <div className="vital-meta">
                <span className="vital-label">LOCATION</span>
                <span className="vital-value">{sessionState?.location || 'Unknown Realm'}</span>
              </div>
            </div>

            <div className="vital-item mood-vital">
              <span className="vital-icon">👁️</span>
              <div className="vital-meta">
                <span className="vital-label">DISPOSITION</span>
                <span className="vital-value">{sessionState?.mood || 'Wary'}</span>
              </div>
            </div>

            <div className="vital-item bar-vital">
              <div className="bar-header">
                <span className="vital-label">HEALTH</span>
                <span className="vital-numeric">
                  {sessionState?.hp ?? 100} / {sessionState?.max_hp ?? 100}
                </span>
              </div>
              <div className="bar-track hp-track">
                <div className="bar-fill hp-fill" style={{ width: `${hpPercent}%` }} />
              </div>
            </div>

            <div className="vital-item bar-vital">
              <div className="bar-header">
                <span className="vital-label">FOCUS</span>
                <span className="vital-numeric">
                  {sessionState?.focus ?? 50} / {sessionState?.max_focus ?? 50}
                </span>
              </div>
              <div className="bar-track focus-track">
                <div className="bar-fill focus-fill" style={{ width: `${focusPercent}%` }} />
              </div>
            </div>
          </div>

          {error && (
            <div className="main-error-banner" role="alert">
              <span>⚠️ {error}</span>
              <button type="button" onClick={() => setError(null)}>✕</button>
            </div>
          )}

          {/* Narrative Log & Active Stream Area */}
          <div className="narrative-container">
            {storyTurns.map((turn, idx) => (
              <article key={idx} className="story-turn-card">
                {turn.player_action && (
                  <div className="player-action-block">
                    <span className="player-action-label">Your Action (Turn {turn.turn_number}):</span>
                    <blockquote className="player-action-quote">
                      "{turn.player_action}"
                    </blockquote>
                  </div>
                )}

                {/* Recalled NPC Memory Alert Banner */}
                {turn.recalled_memory && (
                  <div className="recalled-memory-banner">
                    <span className="memory-sparkle">💭</span>
                    <div className="memory-details">
                      <strong>{turn.recalled_memory.npc_name} remembers:</strong>
                      <span> "{turn.recalled_memory.content}"</span>
                      <span className="memory-score">
                        (relevance: {Math.round(turn.recalled_memory.score * 100)}%)
                      </span>
                    </div>
                  </div>
                )}

                {/* Narrative Prose */}
                <div className="narration-prose">
                  {turn.narration}
                </div>

                {/* Continuity Guard Verification Badge */}
                {turn.continuity && (
                  <div className={`continuity-badge ${turn.continuity.has_contradiction ? 'contradiction' : 'verified'}`}>
                    <span className="continuity-icon">
                      {turn.continuity.has_contradiction ? '⚡' : '🛡️'}
                    </span>
                    <span>
                      {turn.continuity.has_contradiction
                        ? `Continuity Contradiction: ${turn.continuity.reason}`
                        : 'Continuity Verified'}
                    </span>
                  </div>
                )}
              </article>
            ))}

            {/* Live Streaming Active Turn */}
            {isStreaming && (
              <article className="story-turn-card streaming-turn">
                <div className="streaming-header">
                  <span className="spinner-small" /> The Dungeon Master speaks...
                </div>
                <div className="narration-prose">
                  {currentStreamingText}
                  <span className="streaming-cursor">▋</span>
                </div>
              </article>
            )}

            <div ref={narrativeEndRef} />
          </div>

          {/* Quick Suggestion Chips */}
          <div className="suggestion-chips">
            <span className="chips-label">Inspirations:</span>
            <button
              type="button"
              className="chip-btn"
              disabled={isStreaming}
              onClick={() => setActionInput('Search the mossy stone alcove for tools.')}
            >
              🔍 Search the alcove
            </button>
            <button
              type="button"
              className="chip-btn"
              disabled={isStreaming}
              onClick={() => setActionInput('Ask Kael if he knows where the river is shallow enough to ford.')}
            >
              💬 Speak with Kael
            </button>
            <button
              type="button"
              className="chip-btn"
              disabled={isStreaming}
              onClick={() => setActionInput('Attack the bog hound lunging from the marsh with a spear.')}
            >
              ⚔️ Attack the hound
            </button>
            <button
              type="button"
              className="chip-btn"
              disabled={isStreaming}
              onClick={() => setActionInput('Scout the old imperial highway for alternative crossings.')}
            >
              🧭 Scout the highway
            </button>
          </div>

          {/* Player Action Input Form */}
          <form onSubmit={handleActionSubmit} className="action-input-form">
            <div className="input-wrapper">
              <input
                ref={inputRef}
                type="text"
                value={actionInput}
                onChange={(e) => setActionInput(e.target.value)}
                placeholder={
                  activeReplayNodeId
                    ? `Forking alternative action from node ${activeReplayNodeId.slice(0, 8)}...`
                    : 'What do you want to do? (e.g. "Examine the lantern in the gatehouse...")'
                }
                disabled={isStreaming}
                autoFocus
              />
              <button
                type="submit"
                className="btn-primary btn-action-send"
                disabled={isStreaming || !actionInput.trim()}
              >
                {isStreaming ? (
                  <span className="spinner-small" />
                ) : (
                  'Take Action ↵'
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Right Column: World State Panels (Inventory, Quests, NPCs) */}
        <aside className="world-column">
          {/* Inventory Panel */}
          <section className="panel-card">
            <header className="panel-header">
              <h3>🎒 INVENTORY</h3>
              <span className="panel-count">{sessionState?.inventory?.length || 0}</span>
            </header>
            <div className="panel-body">
              {!sessionState?.inventory || sessionState.inventory.length === 0 ? (
                <p className="empty-panel-text">No items in your pack yet.</p>
              ) : (
                <ul className="inventory-list">
                  {sessionState.inventory.map((item) => (
                    <li key={item.id} className="inventory-item">
                      <span className="item-icon">🗡️</span>
                      <div className="item-details">
                        <strong className="item-name">{item.name}</strong>
                        {item.description && (
                          <p className="item-desc">{item.description}</p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {/* Active Quests Panel */}
          <section className="panel-card">
            <header className="panel-header">
              <h3>📜 ACTIVE QUESTS</h3>
              <span className="panel-count">{sessionState?.quests?.length || 0}</span>
            </header>
            <div className="panel-body">
              {!sessionState?.quests || sessionState.quests.length === 0 ? (
                <p className="empty-panel-text">No active quests recorded.</p>
              ) : (
                <ul className="quest-list">
                  {sessionState.quests.map((quest) => (
                    <li key={quest.id} className="quest-item">
                      <div className="quest-title-row">
                        <strong>{quest.title}</strong>
                        <span className={`quest-status-badge status-${quest.status}`}>
                          {quest.status}
                        </span>
                      </div>
                      <p className="quest-desc">{quest.description}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {/* NPCs in Scene Panel */}
          <section className="panel-card">
            <header className="panel-header">
              <h3>👥 NOTABLE NPCS</h3>
              <span className="panel-count">{sessionState?.npcs?.length || 0}</span>
            </header>
            <div className="panel-body">
              {!sessionState?.npcs || sessionState.npcs.length === 0 ? (
                <p className="empty-panel-text">No companions in this scene.</p>
              ) : (
                <ul className="npc-list">
                  {sessionState.npcs.map((npc) => (
                    <li key={npc.id} className="npc-item">
                      <div className="npc-header-row">
                        <strong className="npc-name">{npc.name}</strong>
                        <span className={`relationship-badge label-${npc.relationship_label?.toLowerCase()}`}>
                          {npc.relationship_label} ({npc.relationship_score > 0 ? `+${npc.relationship_score}` : npc.relationship_score})
                        </span>
                      </div>
                      <p className="npc-desc">{npc.description}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
