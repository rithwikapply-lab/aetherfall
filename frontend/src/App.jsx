import React, { useState } from 'react';
import LandingScreen from './components/LandingScreen';
import MainScreen from './components/MainScreen';
import GraphScreen from './components/GraphScreen';
import ChapterOverviewScreen from './components/ChapterOverviewScreen';
import WorldMapScreen from './components/WorldMapScreen';

export default function App() {
  // Simple local state router: "landing" | "main" | "graph" | "chapters" | "map"
  const [view, setView] = useState('landing');
  const [session, setSession] = useState(null);
  const [pendingReplay, setPendingReplay] = useState(null);
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
    setLastSession(newSession);
    try {
      localStorage.setItem('aetherfall_last_session', JSON.stringify(newSession));
    } catch (e) {
      console.warn('Unable to save session to localStorage:', e);
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

  const handleResumeCampaign = (sessionToResume, initialAction = null) => {
    setSession(sessionToResume);
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

  const handleNewCampaign = () => {
    // Keep lastSession in localStorage so player can still resume if desired
    setSession(null);
    setPendingReplay(null);
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
          existingSession={session || lastSession}
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
