import React, { useState } from 'react';
import LandingScreen from './components/LandingScreen';
import MainScreen from './components/MainScreen';
import GraphScreen from './components/GraphScreen';
import ChapterOverviewScreen from './components/ChapterOverviewScreen';
import WorldMapScreen from './components/WorldMapScreen';
import { getSessionState } from './api/client';

export default function App() {
  // Simple local state router: "landing" | "main" | "graph" | "chapters" | "map"
  const [view, setView] = useState('landing');
  const [session, setSession] = useState(null);
  const [pendingReplay, setPendingReplay] = useState(null);
  const [isResuming, setIsResuming] = useState(false);
  const [resumeError, setResumeError] = useState(null);
  const [lastSession, setLastSession] = useState(() => {
    try {
      const saved = localStorage.getItem('aetherfall_last_session');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const handleStartCampaign = (newSession, initialAction = null) => {
    setSession(newSession);
    // Persist only non-authoritative cosmetic pointer (id + display hints)
    const minimalPointer = {
      id: newSession.id,
      title: newSession.title,
      chapter: newSession.chapter,
    };
    setLastSession(minimalPointer);
    try {
      localStorage.setItem('aetherfall_last_session', JSON.stringify(minimalPointer));
    } catch (e) {
      console.warn('Unable to save session pointer to localStorage:', e);
    }
    if (initialAction) {
      setPendingReplay({
        fromNodeId: null,
        defaultActionText: initialAction,
      });
    } else {
      setPendingReplay(null);
    }
    setView('main');
  };

  const handleResumeCampaign = async (sessionPointer, initialAction = null) => {
    if (!sessionPointer?.id) return;
    setIsResuming(true);
    setResumeError(null);
    try {
      // Authoritative database fetch: world state lives in database rows, never in client storage
      const freshState = await getSessionState(sessionPointer.id);
      setSession(freshState);
      const minimalPointer = {
        id: freshState.id,
        title: freshState.title,
        chapter: freshState.chapter,
      };
      setLastSession(minimalPointer);
      try {
        localStorage.setItem('aetherfall_last_session', JSON.stringify(minimalPointer));
      } catch {}

      if (initialAction) {
        setPendingReplay({
          fromNodeId: null,
          defaultActionText: initialAction,
        });
      } else {
        setPendingReplay(null);
      }
      setView('main');
    } catch (err) {
      console.error('Failed to resume session from database:', err);
      // Purge invalid/stale pointer from localStorage so client does not retain ghost pointer
      try {
        localStorage.removeItem('aetherfall_last_session');
      } catch {}
      setLastSession(null);
      setResumeError('Previous campaign could not be found in the database. Please start a new campaign.');
    } finally {
      setIsResuming(false);
    }
  };

  const handleNewCampaign = () => {
    // Keep minimal lastSession pointer in localStorage so player can still resume if desired
    setSession(null);
    setPendingReplay(null);
    setResumeError(null);
    setView('landing');
  };

  const handleNavigateToGraph = () => {
    setView('graph');
  };

  const handleNavigateToChapters = () => {
    setView('chapters');
  };

  const handleNavigateToMap = () => {
    setView('map');
  };

  const handleNavigateToMain = () => {
    setView('main');
  };

  const handleReplayFromNode = ({ fromNodeId, actionText }) => {
    setPendingReplay({
      fromNodeId,
      defaultActionText: actionText,
    });
    setView('main');
  };

  const handleClearPendingReplay = () => {
    setPendingReplay(null);
  };

  return (
    <div className="aetherfall-app">
      {view === 'landing' && (
        <LandingScreen
          onStartCampaign={handleStartCampaign}
          onResumeCampaign={handleResumeCampaign}
          existingSession={lastSession}
          isResuming={isResuming}
          resumeError={resumeError}
        />
      )}

      {view === 'main' && session && (
        <MainScreen
          session={session}
          onNavigateToGraph={handleNavigateToGraph}
          onNavigateToChapters={handleNavigateToChapters}
          onNavigateToMap={handleNavigateToMap}
          onNewCampaign={handleNewCampaign}
          onStartCampaign={handleStartCampaign}
          pendingReplay={pendingReplay}
          onClearPendingReplay={handleClearPendingReplay}
        />
      )}

      {view === 'graph' && session && (
        <GraphScreen
          session={session}
          onNavigateToMain={handleNavigateToMain}
          onReplayFromNode={handleReplayFromNode}
        />
      )}

      {view === 'chapters' && session && (
        <ChapterOverviewScreen
          session={session}
          onNavigateToMain={handleNavigateToMain}
        />
      )}

      {view === 'map' && session && (
        <WorldMapScreen
          session={session}
          onNavigateToMain={handleNavigateToMain}
        />
      )}
    </div>
  );
}
