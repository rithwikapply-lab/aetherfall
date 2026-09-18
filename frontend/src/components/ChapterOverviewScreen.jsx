import React, { useState, useEffect } from 'react';
import { getChapters, getSessionState } from '../api/client';

export default function ChapterOverviewScreen({ session, onNavigateToMain }) {
  const [chapters, setChapters] = useState([]);
  const [sessionState, setSessionState] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;

    async function loadData() {
      setIsLoading(true);
      setError(null);
      try {
        const [chapList, state] = await Promise.all([
          getChapters(),
          session?.id ? getSessionState(session.id) : Promise.resolve(null),
        ]);
        if (!isMounted) return;
        setChapters(chapList);
        setSessionState(state);
      } catch (err) {
        if (isMounted) {
          setError(err.message || 'Failed to load chapter overview data.');
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, [session?.id]);

  const currentChapterNum = sessionState?.chapter_number || session?.chapter_number || 1;
  const completedChapters = sessionState?.completed_chapters || session?.completed_chapters || [];
  const quests = sessionState?.quests || [];

  return (
    <div className="chapter-overview-container">
      {/* Navigation Bar */}
      <header className="main-navbar">
        <div className="navbar-brand">
          <span className="brand-logo">⚔ AETHERFALL</span>
          <span className="brand-title">{sessionState?.title || session?.title}</span>
          <span className="chapter-pill">{sessionState?.chapter || session?.chapter}</span>
        </div>

        <div className="navbar-actions">
          <button
            type="button"
            className="btn-primary btn-return-main"
            onClick={onNavigateToMain}
            title="Return to Story View"
          >
            ← Return to Chronicles
          </button>
        </div>
      </header>

      <main className="chapter-overview-content">
        <header className="chapter-overview-header">
          <div className="landing-badge">CAMPAIGN PROGRESSION</div>
          <h1 className="chapter-overview-title">THE FOUR REVELATIONS</h1>
          <p className="chapter-overview-tagline">
            The full arc of your journey across the Sunken Reach. The road is known; how you survive it is yours to write.
          </p>
        </header>

        {isLoading ? (
          <div className="chapter-loading-state">
            <span className="spinner-small" />
            <p>Consulting the ancient cartographies...</p>
          </div>
        ) : error ? (
          <div className="main-error-banner" role="alert">
            <span>⚠️ {error}</span>
          </div>
        ) : (
          <div className="chapter-timeline-roadmap">
            {chapters.map((chap, idx) => {
              const isCompleted = completedChapters.includes(chap.number) || (sessionState?.is_game_over && sessionState?.game_over_reason === 'victory');
              const isCurrent = !isCompleted && chap.number === currentChapterNum;
              const isUnreached = !isCompleted && !isCurrent;

              // Find current active quest for this chapter
              const matchingQuest = quests.find(
                (q) => q.title.toLowerCase() === chap.completion_quest_title.toLowerCase()
              );

              return (
                <div
                  key={chap.number}
                  className={`chapter-timeline-step ${
                    isCompleted ? 'step-completed' : isCurrent ? 'step-current' : 'step-unreached'
                  }`}
                >
                  {/* Step Connector Node */}
                  <div className="timeline-node-container">
                    <div className="timeline-node">
                      {isCompleted ? (
                        <span className="node-icon check-icon">✓</span>
                      ) : isCurrent ? (
                        <span className="node-icon active-icon">✦</span>
                      ) : (
                        <span className="node-icon lock-icon">{chap.number}</span>
                      )}
                    </div>
                    {idx < chapters.length - 1 && (
                      <div
                        className={`timeline-connector-bar ${
                          isCompleted ? 'connector-completed' : ''
                        }`}
                      />
                    )}
                  </div>

                  {/* Chapter Details Card */}
                  <article className="chapter-roadmap-card">
                    <div className="card-header-row">
                      <span className="chapter-sequence-tag">CHAPTER {chap.number}</span>
                      <span className={`chapter-status-pill pill-${isCompleted ? 'completed' : isCurrent ? 'active' : 'unreached'}`}>
                        {isCompleted
                          ? '✓ COMPLETED'
                          : isCurrent
                          ? '● ACTIVE CHAPTER'
                          : '○ UNREACHED'}
                      </span>
                    </div>

                    <h2 className="chapter-card-title">{chap.title}</h2>

                    <div className="chapter-objective-box">
                      <span className="objective-label">OBJECTIVE:</span>
                      <p className="objective-text">{chap.objective}</p>
                    </div>

                    {isCurrent && (
                      <div className="active-quest-panel">
                        <div className="quest-panel-header">
                          <span className="quest-key-icon">🗝️</span>
                          <span className="quest-panel-title">COMPLETION QUEST</span>
                          <span className="quest-status-badge badge-active">
                            {matchingQuest?.status || 'Active'}
                          </span>
                        </div>
                        <p className="quest-title-display">"{chap.completion_quest_title}"</p>
                        <p className="quest-panel-desc">
                          {matchingQuest?.description || chap.completion_quest_description}
                        </p>
                      </div>
                    )}

                    {isCompleted && (
                      <div className="completed-quest-banner">
                        <span className="check-mark">✓</span>
                        <span>Designated quest completed: <strong>{chap.completion_quest_title}</strong></span>
                      </div>
                    )}

                    {isUnreached && (
                      <div className="unreached-quest-hint">
                        <span className="lock-subtext">Unlocks upon completing Chapter {chap.number - 1}. Target Quest: <em>{chap.completion_quest_title}</em></span>
                      </div>
                    )}
                  </article>
                </div>
              );
            })}
          </div>
        )}

        {/* Back to Game Button */}
        <footer className="chapter-overview-footer">
          <button
            type="button"
            className="btn-primary btn-return-action"
            onClick={onNavigateToMain}
          >
            ← Return to Campaign Chronicle
          </button>
        </footer>
      </main>
    </div>
  );
}
