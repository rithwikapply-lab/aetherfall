import React, { useState, useEffect } from 'react';
import { createSession, getChapters } from '../api/client';

export default function LandingScreen({
  onStartCampaign,
  onResumeCampaign,
  existingSession,
}) {
  const [chapters, setChapters] = useState([]);
  const [loadingChapters, setLoadingChapters] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState(null);
  const [copiedActionIndex, setCopiedActionIndex] = useState(null);

  // Fetch canonical chapters directly from Stage B single source of truth
  useEffect(() => {
    let isMounted = true;
    async function loadChapters() {
      try {
        const data = await getChapters();
        if (isMounted) {
          setChapters(data || []);
          setLoadingChapters(false);
        }
      } catch (err) {
        console.error('Failed to load canonical chapters:', err);
        if (isMounted) {
          setLoadingChapters(false);
        }
      }
    }
    loadChapters();
    return () => {
      isMounted = false;
    };
  }, []);

  // Handler to start a fresh campaign
  const handleBeginFresh = async (initialAction = null) => {
    setIsStarting(true);
    setError(null);
    try {
      const session = await createSession({
        title: 'The Sunken Reach',
        chapter: 'Chapter 1: The Drowned Road',
      });
      onStartCampaign(session, initialAction);
    } catch (err) {
      setError(err.message || 'Failed to initialize campaign. Make sure backend is running.');
      setIsStarting(false);
    }
  };

  // Handler to resume active campaign
  const handleResume = (initialAction = null) => {
    if (existingSession && onResumeCampaign) {
      onResumeCampaign(existingSession, initialAction);
    } else {
      handleBeginFresh(initialAction);
    }
  };

  // Example prompting actions for section 4
  const exampleActions = [
    {
      action: 'Wade through the shallow reeds toward the rusted truck cab to search for dry supplies.',
      tag: 'Investigation & Scavenging',
      icon: '🔍',
    },
    {
      action: 'Sit with your back against a dry rock pillar, bandage your arm, and catch your breath.',
      tag: 'Recovery & Focus Restoration',
      icon: '🌿',
    },
    {
      action: 'Ask Kael quietly why the drowned chapel bell continues to toll across the marsh at dusk.',
      tag: 'Dialogue & NPC Interrogation',
      icon: '💬',
    },
    {
      action: 'Carefully inspect the ancient floodgate runes before touching the rusted iron lever.',
      tag: 'Caution & Lore Inspection',
      icon: '📜',
    },
  ];

  // Handler for clicking example action
  const handleExampleClick = async (actionText, index) => {
    try {
      await navigator.clipboard.writeText(actionText);
    } catch {
      // Ignore clipboard write failures on restricted browsers
    }
    setCopiedActionIndex(index);
    setTimeout(() => {
      setCopiedActionIndex(null);
    }, 2500);

    // If an existing campaign exists, resume with action; otherwise begin fresh
    if (existingSession) {
      handleResume(actionText);
    } else {
      handleBeginFresh(actionText);
    }
  };

  return (
    <div className="landing-page-root">
      {/* Subtle Background Glows */}
      <div className="landing-ambient-glow glow-gold" />
      <div className="landing-ambient-glow glow-blue" />

      {/* Top Navigation Anchor Bar */}
      <nav className="landing-nav-bar" aria-label="Landing Page Navigation">
        <div className="landing-nav-logo">
          <span className="logo-rune">⚔</span>
          <span className="logo-text">AETHERFALL</span>
        </div>
        <div className="landing-nav-links">
          <a href="#journey">Journey</a>
          <a href="#survival">Survival</a>
          <a href="#how-to-play">How to Play</a>
          <a href="#architecture">Architecture</a>
          <a
            href="https://github.com/rithwikapply-lab/aetherfall.git"
            target="_blank"
            rel="noopener noreferrer"
            className="nav-github-link"
          >
            GitHub ↗
          </a>
        </div>
      </nav>

      {/* SECTION 1: HERO */}
      <section className="landing-section hero-section" id="hero">
        <div className="hero-content">
          <div className="hero-badge-row">
            <span className="hero-badge">AI DUNGEON MASTER ENGINE</span>
            <span className="hero-subbadge">RELATIONAL WORLD STATE</span>
          </div>

          <h1 className="hero-title">AETHERFALL</h1>

          <p className="hero-premise">
            The world is a database, not a chat transcript.
          </p>

          <div className="hero-objective-card">
            <span className="objective-prefix">CAMPAIGN OBJECTIVE</span>
            <p className="objective-statement">
              Cross the Drowned Valley, find the ghost-catcher, and reach the source of the flood, alive and sane.
            </p>
          </div>

          {error && (
            <div className="landing-error-banner" role="alert">
              <span className="error-icon">⚠️</span>
              <span>{error}</span>
            </div>
          )}

          <div className="hero-cta-group">
            <button
              type="button"
              className="btn-primary hero-btn-begin"
              onClick={() => handleBeginFresh()}
              disabled={isStarting}
            >
              {isStarting ? (
                <span className="btn-loading">
                  <span className="spinner" /> Seeding Realm...
                </span>
              ) : (
                'Begin Campaign ⚔'
              )}
            </button>

            {existingSession && (
              <button
                type="button"
                className="btn-secondary hero-btn-resume"
                onClick={() => handleResume()}
                disabled={isStarting}
              >
                <span className="resume-icon">➔</span>
                <span className="resume-text">
                  Resume Campaign
                  {existingSession.chapter ? ` (${existingSession.chapter.split(':')[0]})` : ''}
                </span>
              </button>
            )}
          </div>

          {existingSession && (
            <div className="hero-session-preview">
              <span className="preview-label">ACTIVE EXPEDITION:</span>
              <span className="preview-val">
                {existingSession.location || 'The Drowned Valley'} • Turn {existingSession.turn_count || 0} • {existingSession.hp ?? 100} HP
              </span>
            </div>
          )}
        </div>
      </section>

      {/* SECTION 2: YOUR JOURNEY (ROUTE MAP) */}
      <section className="landing-section journey-section" id="journey">
        <div className="section-container">
          <div className="section-header">
            <span className="section-eyebrow">ROUTE MAP</span>
            <h2 className="section-title">Your Journey Through The Deluge</h2>
            <p className="section-framing">
              Every playthrough generates an entirely unique branch of history. What is charted below are the mythic destinations of the campaign—the paths, decisions, and sacrifices between them are unscripted and yours to discover.
            </p>
          </div>

          {loadingChapters ? (
            <div className="loading-chapters-box">
              <span className="spinner" /> Loading canonical route map...
            </div>
          ) : (
            <div className="journey-grid">
              {chapters.map((ch) => (
                <div key={ch.number} className="journey-chapter-card">
                  <div className="chapter-header-row">
                    <span className="chapter-ordinal">CHAPTER {ch.number}</span>
                    <span className="chapter-quest-tag">Primary Destination</span>
                  </div>
                  <h3 className="chapter-name">{ch.title}</h3>
                  <div className="chapter-objective-strip">
                    <span className="strip-label">GOAL</span>
                    <p className="strip-text">{ch.objective}</p>
                  </div>
                  <div className="chapter-quest-detail">
                    <span className="quest-key">KEY MILESTONE:</span>
                    <span className="quest-title">{ch.completion_quest_title}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* SECTION 3: HOW TO SURVIVE */}
      <section className="landing-section survival-section" id="survival">
        <div className="section-container">
          <div className="section-header">
            <span className="section-eyebrow">SYSTEMS & MECHANICS</span>
            <h2 className="section-title">How To Survive</h2>
            <p className="section-framing">
              Health and Focus are tangible resources with immediate, lethal consequences. Every decision carries weight.
            </p>
          </div>

          <div className="survival-grid">
            {/* Health Card */}
            <div className="survival-card card-health">
              <div className="card-top">
                <span className="stat-badge badge-hp">HP • HEALTH</span>
                <span className="stat-cap">Max 100</span>
              </div>
              <h3 className="card-headline">Physical Integrity</h3>
              <p className="card-desc">
                Violent clashes, falling masonry, drowning rapids, and environmental hazards drain Health. Reaching <strong>0 HP results in Mortal Demise</strong>.
              </p>
              <div className="card-attrition-note">
                <span className="note-icon">⏳</span>
                <span><strong>-1 HP per turn</strong> from relentless environmental attrition.</span>
              </div>
            </div>

            {/* Focus Card */}
            <div className="survival-card card-focus">
              <div className="card-top">
                <span className="stat-badge badge-focus">FOCUS • SANITY</span>
                <span className="stat-cap">Max 50</span>
              </div>
              <h3 className="card-headline">Mental Fortitude</h3>
              <p className="card-desc">
                Eldritch whispers, high-stakes tactical judgments, and harrowing psychological strain drain Focus. Reaching <strong>0 Focus causes Spiritual Collapse</strong>.
              </p>
              <div className="card-attrition-note">
                <span className="note-icon">⏳</span>
                <span><strong>-2 Focus per turn</strong> from damp psychic pressure.</span>
              </div>
            </div>

            {/* Rules of Consequence Card */}
            <div className="survival-card card-mechanics-rule">
              <div className="card-top">
                <span className="stat-badge badge-rules">REAL CONSEQUENCES</span>
                <span className="stat-cap">Priority: HP &gt; Focus</span>
              </div>
              <h3 className="card-headline">Actions Are Not Flavor Text</h3>
              <p className="card-desc">
                Reckless, needlessly aggressive, or belligerent actions inflict severe resource penalties assessed by the State-Extraction Agent. Careful positioning, negotiation, and deliberate rest actively restore both vitals.
              </p>
              <div className="card-attrition-note highlight-rule">
                <span className="note-icon">⚖</span>
                <span>If HP and Focus both drop to zero in the same turn, <strong>Mortal Demise takes precedence</strong>.</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 4: HOW TO PLAY (PROMPTING GUIDE) */}
      <section className="landing-section play-section" id="how-to-play">
        <div className="section-container">
          <div className="section-header">
            <span className="section-eyebrow">TACTICAL PLAYBOOK</span>
            <h2 className="section-title">The Prompting Guide</h2>
            <p className="section-framing">
              Aetherfall responds to intentional, grounded roleplay. How you formulate your actions directly guides the narrator and state extractor.
            </p>
          </div>

          <div className="principles-grid">
            <div className="principle-card">
              <div className="principle-num">01</div>
              <h4>Write in Second Person Imperative</h4>
              <p>
                State what you do as an action: <em>"Wade toward the overturned truck and check the cab"</em> rather than <em>"I wonder what is inside the truck."</em>
              </p>
            </div>

            <div className="principle-card">
              <div className="principle-num">02</div>
              <h4>Be Concrete & Specific</h4>
              <p>
                <em>"Search the corpse"</em> gives the narrator little inspiration. <em>"Search the drowned guard for the iron ring Kael mentioned"</em> gives the engine clear narrative traction.
              </p>
            </div>

            <div className="principle-card">
              <div className="principle-num">03</div>
              <h4>Diplomacy Is Real & Cheaper</h4>
              <p>
                Combat is deadly and expensive in HP. Dialogue, questioning, bartering, and deception are fully supported and almost always safer than drawing steel.
              </p>
            </div>

            <div className="principle-card">
              <div className="principle-num">04</div>
              <h4>The World Is Not A Menu</h4>
              <p>
                You are never locked into predefined buttons. The world is generated dynamically—attempt anything plausible within the physical reality of the scene.
              </p>
            </div>

            <div className="principle-card">
              <div className="principle-num">05</div>
              <h4>Observation & Rest Are Valid Turns</h4>
              <p>
                Pausing to bandage wounds, inspect ancient runes, or catch your breath behind a pillar often yields Focus recovery rather than wasting time.
              </p>
            </div>
          </div>

          {/* Interactive Starter Action Chips */}
          <div className="starter-actions-box">
            <div className="starter-header">
              <span className="starter-badge">READY-TO-PLAY STARTERS</span>
              <h3>Click an action to copy it &amp; begin immediately:</h3>
            </div>

            <div className="starter-chips-list">
              {exampleActions.map((ex, idx) => (
                <button
                  key={idx}
                  type="button"
                  className={`example-action-chip ${copiedActionIndex === idx ? 'copied' : ''}`}
                  onClick={() => handleExampleClick(ex.action, idx)}
                  title="Click to copy and launch campaign with this action"
                >
                  <span className="chip-icon">{ex.icon}</span>
                  <div className="chip-body">
                    <span className="chip-tag">{ex.tag}</span>
                    <span className="chip-text">"{ex.action}"</span>
                  </div>
                  <span className="chip-action-indicator">
                    {copiedActionIndex === idx ? '✓ Copied & Starting!' : 'Launch ➔'}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 5: HOW THIS WAS BUILT (TECHNICAL SHOWCASE) */}
      <section className="landing-section architecture-section" id="architecture">
        <div className="section-container">
          <div className="section-header">
            <span className="section-eyebrow">ENGINEERING SHOWCASE</span>
            <h2 className="section-title">How Aetherfall Was Built</h2>
            <p className="section-framing">
              An honest, documented breakdown of the architecture, multi-agent pipeline, relational data structures, and trade-offs.
            </p>
          </div>

          {/* Core Architectural Contrast */}
          <div className="tech-contrast-card">
            <div className="contrast-column failure-column">
              <span className="contrast-pill pill-bad">CHAT WRAPPER PARADIGM</span>
              <h4>Why Flat Transcripts Fail</h4>
              <ul>
                <li>
                  <strong>Quadratic Token Growth:</strong> History balloons with turn count, increasing inference cost and latency.
                </li>
                <li>
                  <strong>Context Dilution:</strong> Facts established 20 turns prior dilute among thousands of tokens, triggering hallucinations.
                </li>
                <li>
                  <strong>Destructive Forking:</strong> Exploring alternative choices requires truncating history, destroying previous timelines.
                </li>
              </ul>
            </div>

            <div className="contrast-column victory-column">
              <span className="contrast-pill pill-good">AETHERFALL PARADIGM</span>
              <h4>Relational Database Truth</h4>
              <ul>
                <li>
                  <strong>Discrete Schema:</strong> `GameSession`, `StoryNode`, `InventoryItem`, `Quest`, `NPC`, and `NPCMemoryEntry`.
                </li>
                <li>
                  <strong>Branching As A Tree:</strong> Self-referential `parent_id` foreign keys preserve all branches permanently.
                </li>
                <li>
                  <strong>Deterministic Memory:</strong> Lexical overlap scoring retrieves salient facts in &lt;1ms without vector DB overhead.
                </li>
              </ul>
            </div>
          </div>

          {/* Four-Agent Pipeline Sequence */}
          <div className="pipeline-walkthrough">
            <h3 className="subheading-accent">The Four-Agent Turn Pipeline</h3>
            <div className="pipeline-steps-grid">
              <div className="pipeline-step-card">
                <span className="step-tag">AGENT 1</span>
                <h4>NPC Memory Agent</h4>
                <p>
                  Scores scene NPCs using tokenized Jaccard similarity, normalized salience, and recency decay. Explainable token audit without vector embeddings.
                </p>
              </div>

              <div className="pipeline-step-card">
                <span className="step-tag">AGENT 2</span>
                <h4>Narrator Agent</h4>
                <p>
                  Streams rich narrative prose via Server-Sent Events (SSE) over HTTP POST, adhering to the W3C single-leading-space rule for clean formatting.
                </p>
              </div>

              <div className="pipeline-step-card">
                <span className="step-tag">AGENT 3</span>
                <h4>State-Extraction Agent</h4>
                <p>
                  Extracts structured Pydantic `StateDelta` payloads. Commits HP, Focus, inventory mutations, and quests atomically to SQLite/PostgreSQL.
                </p>
              </div>

              <div className="pipeline-step-card">
                <span className="step-tag">AGENT 4</span>
                <h4>Continuity Guard Agent</h4>
                <p>
                  Two-tier architecture: Tier-1 short-circuits with zero latency on opening turns; Tier-2 verifies canon facts along the ancestor chain.
                </p>
              </div>
            </div>
          </div>

          {/* Architecture Proofs & Limitations Grid */}
          <div className="tech-details-grid">
            <div className="tech-detail-card">
              <h4>Story Graph &amp; Branching</h4>
              <p>
                Every story node points to its ancestor. Choosing "Replay from here" forks a sibling child node under that ancestor, dynamically classifying nodes into <code>current</code>, <code>path</code>, <code>alternate</code>, and <code>abandoned</code>.
              </p>
            </div>

            <div className="tech-detail-card">
              <h4>Test Isolation &amp; Proofs</h4>
              <p>
                51 automated tests execute in ~1.4s with zero network dependencies using <code>MockLLMClient</code> and ephemeral databases. Deliberate-break validation actively proved test rigor.
              </p>
            </div>

            <div className="tech-detail-card limitations-card">
              <h4>Documented Limitations</h4>
              <p>
                Mock mode uses deterministic keyword hashing. Sessions are partitioned by UUID without user auth. Redis is provisioned but unwired. The SVG graph layout is suited for demo campaigns with dozens of nodes, not hundreds.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* SECTION 6: FOOTER */}
      <footer className="landing-footer" id="footer">
        <div className="footer-content">
          <div className="footer-brand">
            <span className="footer-logo">⚔ AETHERFALL</span>
            <p className="footer-tagline">
              An architectural demonstration of relational database-backed generative interactive fiction.
            </p>
          </div>
          <div className="footer-links">
            <a
              href="https://github.com/rithwikapply-lab/aetherfall.git"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary footer-repo-btn"
            >
              View GitHub Repository ↗
            </a>
            <span className="footer-tech-stack">FastAPI • SQLAlchemy 2.0 • React • Vite</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
