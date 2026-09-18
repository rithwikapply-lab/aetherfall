import React, { useState } from 'react';
import LandingScreen from './components/LandingScreen';
import MainScreen from './components/MainScreen';
import GraphScreen from './components/GraphScreen';

export default function App() {
  // Simple local state router: "landing" | "main" | "graph"
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
          onNewCampaign={handleNewCampaign}
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
    </div>
  );
}
