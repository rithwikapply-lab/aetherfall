import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  createSession,
  getSessionState,
  getStoryNodeDetail,
  getWorldMap,
  streamTurnAction,
} from '../api/client';

export default function MainScreen({
  session,
  onNavigateToGraph,
  onNavigateToChapters,
  onNavigateToMap,
  onNewCampaign,
  onStartCampaign,
  pendingReplay, // { fromNodeId, defaultActionText } if returning from Graph screen
  onClearPendingReplay,
}) {
  // Initialize with authoritative session data if passed from fresh backend fetch
  const [sessionState, setSessionState] = useState(session || null);
  const [storyTurns, setStoryTurns] = useState([]);
  const [currentStreamingText, setCurrentStreamingText] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [actionInput, setActionInput] = useState('');
  const [activeReplayNodeId, setActiveReplayNodeId] = useState(null);
  const [lastTurnResult, setLastTurnResult] = useState(null);
  const [error, setError] = useState(null);
  const [isRestarting, setIsRestarting] = useState(false);

  // Floating delta indicators
  const [hpIndicator, setHpIndicator] = useState(null);
  const [focusIndicator, setFocusIndicator] = useState(null);

  // Chapter advancement interstitial
  const [chapterTransition, setChapterTransition] = useState(null);

  // Minimap state
  const [minimapData, setMinimapData] = useState(null);

  const narrativeEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll narration container on new text
  const scrollToBottom = () => {
    narrativeEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [storyTurns, currentStreamingText]);

  // Floating indicators auto-fade
  useEffect(() => {
    if (!hpIndicator) return;
    const timer = setTimeout(() => {
      setHpIndicator(null);
    }, 4500);
    return () => clearTimeout(timer);
  }, [hpIndicator]);

  useEffect(() => {
    if (!focusIndicator) return;
    const timer = setTimeout(() => {
      setFocusIndicator(null);
    }, 4500);
    return () => clearTimeout(timer);
  }, [focusIndicator]);

  // Chapter transition interstitial auto-advance after 7 seconds
  useEffect(() => {
    if (!chapterTransition) return;
    const timer = setTimeout(() => {
      setChapterTransition(null);
    }, 7000);
    return () => clearTimeout(timer);
  }, [chapterTransition]);

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

  // Check if we came with a pending action or from Graph screen with a replay fork
  useEffect(() => {
    if (pendingReplay) {
      if (pendingReplay.fromNodeId) {
        setActiveReplayNodeId(pendingReplay.fromNodeId);
      }
      if (pendingReplay.defaultActionText) {
        setActionInput(pendingReplay.defaultActionText);
      }
      onClearPendingReplay?.();
    }
  }, [pendingReplay, onClearPendingReplay]);

  // Initial load: fetch map data so minimap shows immediately on resume
  useEffect(() => {
    if (!session?.id) return;
    let isMounted = true;
    getWorldMap(session.id)
      .then((mapData) => { if (isMounted) setMinimapData(mapData); })
      .catch(() => {}); // non-critical
    return () => { isMounted = false; };
  }, [session?.id]);

  // Persist minimal non-authoritative cosmetic pointer for landing screen button
  useEffect(() => {
    if (sessionState?.id) {
      try {
        localStorage.setItem(
          'aetherfall_last_session',
          JSON.stringify({
            id: sessionState.id,
            title: sessionState.title,
            chapter: sessionState.chapter,
          })
        );
      } catch (e) {
        console.warn('Unable to persist session pointer to localStorage:', e);
      }
    }
  }, [sessionState?.id, sessionState?.title, sessionState?.chapter]);

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

          // Trigger floating indicators for HP and Focus if non-zero
          const delta = turnResult.state_delta;
          const rawHpDelta = delta.hp_delta || delta.hp_change || 0;
          const rawFocusDelta = delta.focus_delta || delta.focus_change || 0;

          if (rawHpDelta !== 0) {
            setHpIndicator({
              delta: rawHpDelta,
              reason: delta.hp_delta_reason,
              isPositive: rawHpDelta > 0,
              key: Date.now(),
            });
          }
          if (rawFocusDelta !== 0) {
            setFocusIndicator({
              delta: rawFocusDelta,
              reason: delta.focus_delta_reason,
              isPositive: rawFocusDelta > 0,
              key: Date.now() + 1,
            });
          }

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

          // Chapter transition detection
          if (turnResult.chapter_advanced) {
            setChapterTransition({
              chapterNumber: turnResult.chapter_number,
              title: turnResult.chapter,
              objective: turnResult.chapter_objective || 'Pursue the next phase of the campaign.',
            });
          }

          // Immediate local update if game over
          if (turnResult.is_game_over) {
            setSessionState((prev) => ({
              ...(prev || {}),
              location: turnResult.location || prev?.location,
              hp: turnResult.hp,
              focus: turnResult.focus,
              turn_count: turnResult.turn_count,
              chapter_number: turnResult.chapter_number,
              chapter: turnResult.chapter,
              completed_chapters: turnResult.completed_chapters,
              is_game_over: true,
              game_over_reason: turnResult.game_over_reason,
              game_over_summary: turnResult.game_over_summary,
            }));
          }

          // Refresh full denormalized world state (inventory, quests, NPCs, stats)
          try {
            const updatedState = await getSessionState(session.id);
            setSessionState(updatedState);
          } catch (e) {
            console.error('Failed to reload state after turn:', e);
          }

          // Refresh minimap after each turn
          try {
            const mapData = await getWorldMap(session.id);
            setMinimapData(mapData);
          } catch (e) {
            // Minimap is non-critical; swallow silently
          }
        },
        onError: async (err) => {
          setIsStreaming(false);
          // React to HTTP 400 or game over rejection from the action endpoint
          if (err.status === 400 || (err.message && err.message.toLowerCase().includes('ended'))) {
            try {
              const freshState = await getSessionState(session.id);
              if (freshState.is_game_over) {
                setSessionState(freshState);
                return; // Suppress generic error banner since game-over screen will render
              }
            } catch (fetchErr) {
              console.error('Failed to sync game-over state:', fetchErr);
            }
          }
          setError(err.message || 'Stream connection interrupted.');
        },
      });
    } catch (err) {
      setIsStreaming(false);
      // React to HTTP 400 rejection from streamTurnAction
      if (err.status === 400 || (err.message && err.message.toLowerCase().includes('ended'))) {
        try {
          const freshState = await getSessionState(session.id);
          if (freshState.is_game_over) {
            setSessionState(freshState);
            return;
          }
        } catch (fetchErr) {
          console.error('Failed to sync game-over state:', fetchErr);
        }
      }
      setError(err.message || 'Action failed to execute.');
    }
  };

  // Start a fresh campaign from game-over screen
  const handleStartNewCampaign = async () => {
    setIsRestarting(true);
    try {
      const freshSession = await createSession();
      if (onStartCampaign) {
        onStartCampaign(freshSession);
      } else {
        onNewCampaign?.();
      }
    } catch (err) {
      console.error('Failed to create new session from game-over screen:', err);
      onNewCampaign?.();
    } finally {
      setIsRestarting(false);
    }
  };

  const maxHp = sessionState?.max_hp || 100;
  const maxFocus = sessionState?.max_focus || 50;
  const currentHp = sessionState?.hp ?? maxHp;
  const currentFocus = sessionState?.focus ?? maxFocus;

  const hpPercent = Math.max(0, Math.min(100, Math.round((currentHp / maxHp) * 100)));
  const focusPercent = Math.max(0, Math.min(100, Math.round((currentFocus / maxFocus) * 100)));

  // Color threshold calculation: default > 40%, amber 20-40%, red < 20%
  const getThresholdClass = (percent, defaultType) => {
    if (percent < 20) return 'threshold-red';
    if (percent <= 40) return 'threshold-amber';
    return defaultType === 'hp' ? 'threshold-default-hp' : 'threshold-default-focus';
  };

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
            className="btn-chapter-nav"
            onClick={onNavigateToChapters}
            title="Open Chapter Progression Roadmap"
          >
            <span className="nav-icon">📜</span> Chapters
          </button>
          <button
            type="button"
            className="btn-map-nav"
            onClick={onNavigateToMap}
            title="Open World Map"
          >
            <span className="nav-icon">🗺</span> Map
          </button>
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
                  {currentHp} / {maxHp}
                </span>
              </div>
              <div className="bar-track hp-track">
                <div
                  className={`bar-fill ${getThresholdClass(hpPercent, 'hp')}`}
                  style={{ width: `${hpPercent}%` }}
                />
              </div>
              {hpIndicator && (
                <div
                  key={hpIndicator.key}
                  className={`delta-floating-indicator ${hpIndicator.isPositive ? 'positive' : 'negative'}`}
                >
                  <span className="indicator-delta">
                    {hpIndicator.isPositive ? `+${hpIndicator.delta}` : hpIndicator.delta} HP
                  </span>
                  {hpIndicator.reason && (
                    <span className="indicator-reason">
                      {' — '}{hpIndicator.reason}
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className="vital-item bar-vital">
              <div className="bar-header">
                <span className="vital-label">FOCUS</span>
                <span className="vital-numeric">
                  {currentFocus} / {maxFocus}
                </span>
              </div>
              <div className="bar-track focus-track">
                <div
                  className={`bar-fill ${getThresholdClass(focusPercent, 'focus')}`}
                  style={{ width: `${focusPercent}%` }}
                />
              </div>
              {focusIndicator && (
                <div
                  key={focusIndicator.key}
                  className={`delta-floating-indicator ${focusIndicator.isPositive ? 'positive' : 'negative'}`}
                >
                  <span className="indicator-delta">
                    {focusIndicator.isPositive ? `+${focusIndicator.delta}` : focusIndicator.delta} Focus
                  </span>
                  {focusIndicator.reason && (
                    <span className="indicator-reason">
                      {' — '}{focusIndicator.reason}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {error && (
            <div className="main-error-banner" role="alert">
              <span>⚠️ {error}</span>
              <button type="button" onClick={() => setError(null)}>✕</button>
            </div>
          )}

          {/* Full-width Interstitial Chapter Transition Card */}
          {chapterTransition && (
            <div className="chapter-interstitial-card" role="dialog" aria-label="Chapter Advancement">
              <div className="interstitial-badge">✨ CHAPTER ADVANCEMENT</div>
              <h2 className="interstitial-title">{chapterTransition.title}</h2>
              <div className="interstitial-objective-box">
                <span className="objective-label">PRIMARY OBJECTIVE</span>
                <p className="objective-text">{chapterTransition.objective}</p>
              </div>
              <div className="interstitial-actions">
                <button
                  type="button"
                  className="btn-primary btn-interstitial-dismiss"
                  onClick={() => setChapterTransition(null)}
                >
                  Continue Journey ➔
                </button>
                <span className="interstitial-hint">(Auto-advancing shortly...)</span>
              </div>
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

          {/* Action Input Area OR Game-Over End Screen */}
          {sessionState?.is_game_over ? (
            <div className={`game-over-screen ${sessionState.game_over_reason === 'collapse' ? 'theme-collapse' : sessionState.game_over_reason === 'victory' ? 'theme-victory' : 'theme-death'}`}>
              <div className="game-over-badge">
                {sessionState.game_over_reason === 'victory'
                  ? '🏆 CAMPAIGN VICTORIOUS'
                  : sessionState.game_over_reason === 'death'
                  ? '☠ MORTAL DEMISE'
                  : '👁 SPIRITUAL COLLAPSE'}
              </div>
              <h2 className="game-over-headline">
                {sessionState.game_over_reason === 'victory'
                  ? "The Reach's End"
                  : sessionState.game_over_reason === 'death'
                  ? 'You Died'
                  : 'You Broke'}
              </h2>

              {sessionState.game_over_summary && (
                <p className="game-over-summary">
                  {sessionState.game_over_summary}
                </p>
              )}

              <div className="game-over-meta">
                <div className="meta-card">
                  <span className="meta-label">
                    {sessionState.game_over_reason === 'victory' ? 'CHAPTERS COMPLETED' : 'FINAL CHAPTER'}
                  </span>
                  <span className="meta-val">
                    {sessionState.game_over_reason === 'victory' ? '4 / 4 (All Complete)' : (sessionState.chapter || session?.chapter)}
                  </span>
                </div>
                <div className="meta-card">
                  <span className="meta-label">
                    {sessionState.game_over_reason === 'victory' ? 'TOTAL TURNS' : 'TURNS SURVIVED'}
                  </span>
                  <span className="meta-val">{sessionState.turn_count || 0}</span>
                </div>
                <div className="meta-card">
                  <span className="meta-label">
                    {sessionState.game_over_reason === 'victory' ? 'VICTORY AT' : 'DEMISE AT'}
                  </span>
                  <span className="meta-val">{sessionState.location || 'The Sunken Crossroads'}</span>
                </div>
              </div>

              <div className="game-over-actions">
                <button
                  type="button"
                  className="btn-primary btn-game-over-restart"
                  onClick={handleStartNewCampaign}
                  disabled={isRestarting}
                >
                  {isRestarting ? (
                    <span className="spinner-small" />
                  ) : (
                    '⚔ Start New Campaign'
                  )}
                </button>
              </div>
            </div>
          ) : (
            <>
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
            </>
          )}
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

          {/* World Minimap — non-interactive, click opens full Map screen */}
          <section className="panel-card minimap-panel">
            <header className="panel-header">
              <h3>🗺 MINIMAP</h3>
              <button
                type="button"
                className="minimap-expand-btn"
                onClick={onNavigateToMap}
                title="Open full World Map"
              >
                Expand ↗
              </button>
            </header>
            <div
              className="minimap-body"
              onClick={onNavigateToMap}
              title="Click to open full World Map"
              style={{ cursor: 'pointer' }}
            >
              {minimapData && minimapData.nodes.length > 0 ? (
                <MinimapSVG mapData={minimapData} />
              ) : (
                <p className="empty-panel-text minimap-hint">
                  {minimapData ? 'No locations discovered yet.' : 'Play a turn to build the map.'}
                </p>
              )}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

// ── Inline Minimap SVG ──────────────────────────────────────────────────────
const CHAPTER_COLORS_MINI = {
  1: '#c9a84c', 2: '#4ab8a0', 3: '#d9614c', 4: '#9b59b6',
};

function MinimapSVG({ mapData }) {
  const W = 220;
  const H = 130;
  const R = 14;

  const currentNode = mapData.nodes.find((n) => n.is_current);
  if (!currentNode) return null;

  // Show current + immediate neighbours only
  const connectedIds = new Set();
  mapData.edges.forEach((e) => {
    if (e.source_id === currentNode.id) connectedIds.add(e.target_id);
    if (e.target_id === currentNode.id) connectedIds.add(e.source_id);
  });
  const visibleNodes = mapData.nodes.filter(
    (n) => n.id === currentNode.id || connectedIds.has(n.id)
  ).slice(0, 5); // cap at 5 to avoid cramping

  // Radial arrangement: current in center, neighbours spaced around
  const positions = {};
  positions[currentNode.id] = { x: W / 2, y: H / 2 };
  const neighbours = visibleNodes.filter((n) => n.id !== currentNode.id);
  neighbours.forEach((n, i) => {
    const angle =
      neighbours.length === 1
        ? Math.PI // place single neighbour horizontally to the left
        : (2 * Math.PI * i) / neighbours.length - Math.PI / 2;
    positions[n.id] = {
      x: W / 2 + 60 * Math.cos(angle),
      y: H / 2 + (neighbours.length === 1 ? 0 : 38 * Math.sin(angle)),
    };
  });

  const visibleEdges = mapData.edges.filter(
    (e) => positions[e.source_id] && positions[e.target_id]
  );

  return (
    <svg width={W} height={H} className="minimap-svg" aria-hidden="true">
      {/* Edges */}
      {visibleEdges.map((e) => {
        const src = positions[e.source_id];
        const tgt = positions[e.target_id];
        return (
          <line
            key={`${e.source_id}-${e.target_id}`}
            x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
            stroke="rgba(255,255,255,0.18)" strokeWidth={1.5}
          />
        );
      })}
      {/* Nodes */}
      {visibleNodes.map((n) => {
        const pos = positions[n.id];
        const color = CHAPTER_COLORS_MINI[n.chapter_number] || '#c9a84c';
        const isCurr = n.id === currentNode.id;
        return (
          <g key={n.id} transform={`translate(${pos.x},${pos.y})`}>
            {isCurr && <circle r={R + 5} fill="none" stroke={color} strokeWidth={1.5} opacity={0.5} />}
            <circle
              r={R}
              fill={n.visited ? color : 'transparent'}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray={n.visited ? 'none' : '4 3'}
              opacity={n.visited ? 1 : 0.55}
            />
            <text
              textAnchor="middle"
              dy={R + 10}
              fontSize="8"
              fill="#b8a88a"
              style={{ fontFamily: 'Inter, sans-serif', pointerEvents: 'none' }}
            >
              {n.name.length > 12 ? n.name.slice(0, 11) + '…' : n.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
