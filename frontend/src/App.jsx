import React, { useState } from 'react';
import LandingScreen from './components/LandingScreen';
import MainScreen from './components/MainScreen';
import GraphScreen from './components/GraphScreen';
import ChapterOverviewScreen from './components/ChapterOverviewScreen';

export default function App() {
  // Simple local state router: "landing" | "main" | "graph" | "chapters"
  const [view, setView] = useState('landing');
  const [session, setSession] = useState(null);
  const [pendingReplay, setPendingReplay] = useState(null);

  const handleStartCampaign = (newSession) => {
    setSession(newSession);
    setPendingReplay(null);
    setView('main');
  };

  const handleNewCampaign = () => {
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
        <LandingScreen onStartCampaign={handleStartCampaign} />
      )}

      {view === 'main' && session && (
        <MainScreen
          session={session}
          onNavigateToGraph={handleNavigateToGraph}
          onNavigateToChapters={handleNavigateToChapters}
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
    </div>
  );
}
