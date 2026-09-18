import React, { useState } from 'react';
import { createSession } from '../api/client';

export default function LandingScreen({ onStartCampaign }) {
  const [title, setTitle] = useState('The Sunken Reach');
  const [chapter, setChapter] = useState('Chapter 1: The Drowned Road');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const session = await createSession({ title, chapter });
      onStartCampaign(session);
    } catch (err) {
      setError(err.message || 'Failed to initialize campaign. Make sure backend is running.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="landing-container">
      <div className="landing-stars-overlay" />

      <main className="landing-card">
        <header className="landing-header">
          <div className="landing-badge">AI DUNGEON MASTER ENGINE</div>
          <h1 className="landing-title">AETHERFALL</h1>
          <p className="landing-tagline">
            The world is a database, not a chat transcript.
          </p>
        </header>

        <section className="landing-lore">
          <p>
            Experience an interactive dark-fantasy narrative engine built on immutable relational truth.
            Every decision branches into a persistent story graph, NPCs recall encounters through lexical salience,
            and an automated Continuity Guard defends the canon.
          </p>
        </section>

        {error && (
          <div className="landing-error" role="alert">
            <span className="error-icon">⚠️</span>
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="landing-form">
          <div className="form-group">
            <label htmlFor="campaign-title">Campaign Chronicle Title</label>
            <input
              id="campaign-title"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. The Sunken Reach"
              required
              disabled={isLoading}
            />
          </div>

          <div className="form-group">
            <label htmlFor="campaign-chapter">Opening Chapter</label>
            <input
              id="campaign-chapter"
              type="text"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
              placeholder="e.g. Chapter 1: The Drowned Road"
              required
              disabled={isLoading}
            />
          </div>

          <button
            type="submit"
            className="btn-primary btn-begin"
            disabled={isLoading}
          >
            {isLoading ? (
              <span className="btn-loading">
                <span className="spinner" /> Seeding Realm...
              </span>
            ) : (
              'Begin Journey ⚔'
            )}
          </button>
        </form>

        <footer className="landing-features">
          <div className="feature-item">
            <span className="feature-icon">🌿</span>
            <div>
              <strong>Branching Story Graph</strong>
              <p>Replay from earlier nodes to fork new timelines.</p>
            </div>
          </div>
          <div className="feature-item">
            <span className="feature-icon">📜</span>
            <div>
              <strong>Explainable Memory</strong>
              <p>Deterministic token-overlap retrieval for NPC recall.</p>
            </div>
          </div>
          <div className="feature-item">
            <span className="feature-icon">🛡️</span>
            <div>
              <strong>Continuity Guard</strong>
              <p>Canon facts checked to prevent LLM contradictions.</p>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
