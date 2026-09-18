import React, { useState, useEffect, useMemo } from 'react';
import { getStoryGraph, getStoryNodeDetail } from '../api/client';

export default function GraphScreen({
  session,
  onNavigateToMain,
  onReplayFromNode,
}) {
  const [graphData, setGraphData] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [selectedNodeDetail, setSelectedNodeDetail] = useState(null);
  const [replayActionText, setReplayActionText] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [error, setError] = useState(null);

  // Load story graph on mount
  useEffect(() => {
    if (!session?.id) return;
    let isMounted = true;

    async function loadGraph() {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getStoryGraph(session.id);
        if (!isMounted) return;
        setGraphData(data);

        // Default select current active leaf node or first node
        const activeNode = data.nodes.find((n) => n.status === 'current') || data.nodes[0];
        if (activeNode) {
          setSelectedNodeId(activeNode.id);
        }
      } catch (err) {
        if (isMounted) setError(err.message || 'Failed to load story graph.');
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadGraph();
    return () => {
      isMounted = false;
    };
  }, [session?.id]);

  // Load detailed node facts & narration when selectedNodeId changes
  useEffect(() => {
    if (!session?.id || !selectedNodeId) return;
    let isMounted = true;

    async function loadDetail() {
      setIsDetailLoading(true);
      try {
        const detail = await getStoryNodeDetail(session.id, selectedNodeId);
        if (isMounted) {
          setSelectedNodeDetail(detail);
          setReplayActionText('');
        }
      } catch (err) {
        console.error('Failed to load node detail:', err);
      } finally {
        if (isMounted) setIsDetailLoading(false);
      }
    }

    loadDetail();
    return () => {
      isMounted = false;
    };
  }, [session?.id, selectedNodeId]);

  // Compute 2D coordinates for tree visualization
  const { nodePositions, connections, svgBounds } = useMemo(() => {
    if (!graphData?.nodes || graphData.nodes.length === 0) {
      return { nodePositions: [], connections: [], svgBounds: { width: 800, height: 500 } };
    }

    const NODE_WIDTH = 200;
    const NODE_HEIGHT = 90;
    const HORIZONTAL_SPACING = 280;
    const VERTICAL_SPACING = 140;

    // Group nodes by turn_number (depth along X axis)
    const nodesByTurn = {};
    graphData.nodes.forEach((node) => {
      const turn = node.turn_number;
      if (!nodesByTurn[turn]) nodesByTurn[turn] = [];
      nodesByTurn[turn].push(node);
    });

    const positions = {};
    const maxTurn = Math.max(...Object.keys(nodesByTurn).map(Number));

    // Assign Y coordinates per depth column
    let maxRows = 1;
    Object.keys(nodesByTurn).forEach((turnStr) => {
      const turn = Number(turnStr);
      const columnNodes = nodesByTurn[turn];
      maxRows = Math.max(maxRows, columnNodes.length);

      columnNodes.forEach((node, rowIdx) => {
        positions[node.id] = {
          node,
          x: turn * HORIZONTAL_SPACING + 50,
          y: rowIdx * VERTICAL_SPACING + 60,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
        };
      });
    });

    // Build curve connections from parent to child
    const edges = [];
    graphData.nodes.forEach((node) => {
      if (node.parent_id && positions[node.parent_id] && positions[node.id]) {
        const parentPos = positions[node.parent_id];
        const childPos = positions[node.id];

        const x1 = parentPos.x + NODE_WIDTH;
        const y1 = parentPos.y + NODE_HEIGHT / 2;
        const x2 = childPos.x;
        const y2 = childPos.y + NODE_HEIGHT / 2;
        const midX = (x1 + x2) / 2;

        const pathD = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;

        // Determine edge stroke styling based on child status
        let edgeClass = 'edge-abandoned';
        if (childPos.node.status === 'current' || childPos.node.status === 'path') {
          edgeClass = 'edge-path';
        } else if (childPos.node.status === 'alternate') {
          edgeClass = 'edge-alternate';
        }

        edges.push({
          id: `${node.parent_id}->${node.id}`,
          d: pathD,
          className: edgeClass,
          status: childPos.node.status,
        });
      }
    });

    const width = Math.max(900, (maxTurn + 1) * HORIZONTAL_SPACING + 150);
    const height = Math.max(550, maxRows * VERTICAL_SPACING + 150);

    return {
      nodePositions: Object.values(positions),
      connections: edges,
      svgBounds: { width, height },
    };
  }, [graphData]);

  const handleReplaySubmit = (e) => {
    e.preventDefault();
    if (!selectedNodeId) return;
    const action = replayActionText.trim() || 'Explore an alternative path from this point.';
    onReplayFromNode({
      fromNodeId: selectedNodeId,
      actionText: action,
    });
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'current':
        return 'CURRENT LEAF';
      case 'path':
        return 'ACTIVE PATH';
      case 'alternate':
        return 'ALTERNATE FORK';
      case 'abandoned':
        return 'ABANDONED BRANCH';
      default:
        return status?.toUpperCase();
    }
  };

  return (
    <div className="graph-layout">
      {/* Graph Screen Header */}
      <header className="graph-navbar">
        <div className="graph-nav-left">
          <button
            type="button"
            className="btn-back-story"
            onClick={onNavigateToMain}
          >
            ← Back to Story
          </button>
          <div className="graph-title-block">
            <h2>STORY GRAPH EXPLORER</h2>
            <span className="graph-node-counter">
              {graphData?.nodes?.length || 0} Total Story Nodes
            </span>
          </div>
        </div>

        {/* Legend for 4 Node Statuses */}
        <div className="graph-legend">
          <div className="legend-item">
            <span className="legend-dot status-current-dot" />
            <span>Current Leaf</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot status-path-dot" />
            <span>Active Path</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot status-alternate-dot" />
            <span>Alternate Fork</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot status-abandoned-dot" />
            <span>Abandoned</span>
          </div>
        </div>
      </header>

      {/* Main Graph Content Area */}
      <div className="graph-body">
        {/* Interactive SVG Tree Canvas */}
        <div className="graph-canvas-container">
          {isLoading && (
            <div className="graph-loading-overlay">
              <span className="spinner" /> Loading Story Graph...
            </div>
          )}

          {error && (
            <div className="graph-error-banner" role="alert">
              <span>⚠️ {error}</span>
            </div>
          )}

          <div className="graph-scroll-area">
            <svg
              className="graph-svg"
              width={svgBounds.width}
              height={svgBounds.height}
              style={{ minWidth: svgBounds.width, minHeight: svgBounds.height }}
            >
              <defs>
                {/* Glow filter for active golden path */}
                <filter id="gold-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="3" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              {/* Connecting Edges */}
              <g className="edges-layer">
                {connections.map((edge) => (
                  <path
                    key={edge.id}
                    d={edge.d}
                    className={`tree-edge ${edge.className}`}
                  />
                ))}
              </g>

              {/* Node Cards */}
              <g className="nodes-layer">
                {nodePositions.map((pos) => {
                  const node = pos.node;
                  const isSelected = selectedNodeId === node.id;
                  const statusClass = `node-status-${node.status}`;

                  return (
                    <g
                      key={node.id}
                      transform={`translate(${pos.x}, ${pos.y})`}
                      className={`graph-node-group ${statusClass} ${isSelected ? 'selected' : ''}`}
                      onClick={() => setSelectedNodeId(node.id)}
                      style={{ cursor: 'pointer' }}
                    >
                      {/* Node Card Background Rect */}
                      <rect
                        width={pos.width}
                        height={pos.height}
                        rx={10}
                        ry={10}
                        className="node-card-bg"
                      />

                      {/* Header Badge: Turn & Status */}
                      <text x={12} y={24} className="node-turn-text">
                        Turn {node.turn_number}
                      </text>

                      <rect
                        x={pos.width - 80}
                        y={10}
                        width={70}
                        height={18}
                        rx={4}
                        className="status-pill-bg"
                      />
                      <text
                        x={pos.width - 45}
                        y={22}
                        textAnchor="middle"
                        className="status-pill-text"
                      >
                        {node.status}
                      </text>

                      {/* Action / Excerpt Preview */}
                      <text x={12} y={48} className="node-action-preview">
                        {node.player_action
                          ? `"${node.player_action.slice(0, 22)}..."`
                          : 'Opening scene'}
                      </text>

                      <text x={12} y={70} className="node-location-preview">
                        📍 {node.location ? node.location.slice(0, 20) : 'The Sunken Realm'}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>
        </div>

        {/* Right Side Panel: Node Detail & Replay from Here */}
        <aside className="graph-side-panel">
          {selectedNodeDetail ? (
            <div className="node-detail-card">
              <header className="detail-header">
                <div className="detail-badge-row">
                  <span className="detail-turn-badge">
                    Turn {selectedNodeDetail.turn_number}
                  </span>
                  <span className={`detail-status-pill status-${selectedNodeDetail.status}`}>
                    {getStatusLabel(selectedNodeDetail.status)}
                  </span>
                </div>
                <h3 className="detail-location">{selectedNodeDetail.location}</h3>
                <span className="detail-node-id">ID: {selectedNodeDetail.id.slice(0, 12)}...</span>
              </header>

              <div className="detail-body">
                {/* Player Action */}
                {selectedNodeDetail.player_action && (
                  <div className="detail-section">
                    <span className="section-label">PLAYER ACTION:</span>
                    <blockquote className="detail-action-quote">
                      "{selectedNodeDetail.player_action}"
                    </blockquote>
                  </div>
                )}

                {/* Narration Prose */}
                <div className="detail-section">
                  <span className="section-label">CHRONICLE NARRATION:</span>
                  <div className="detail-narration-text">
                    {selectedNodeDetail.narration}
                  </div>
                </div>

                {/* Established Canon Facts */}
                {selectedNodeDetail.facts && selectedNodeDetail.facts.length > 0 && (
                  <div className="detail-section">
                    <span className="section-label">CANON FACTS ESTABLISHED:</span>
                    <ul className="detail-facts-list">
                      {selectedNodeDetail.facts.map((fact, idx) => (
                        <li key={idx} className="fact-item">
                          🛡️ {fact}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Replay from Here Form */}
                <div className="replay-action-box">
                  <span className="replay-box-title">🌿 FORK ALTERNATIVE TIMELINE</span>
                  <p className="replay-box-desc">
                    Replaying from this node creates a new branching path in the story tree.
                    The current timeline will be preserved and labeled as an alternate or abandoned branch.
                  </p>

                  <form onSubmit={handleReplaySubmit} className="replay-form">
                    <input
                      type="text"
                      value={replayActionText}
                      onChange={(e) => setReplayActionText(e.target.value)}
                      placeholder="Enter new diverging action from this turn..."
                      className="replay-input"
                    />
                    <button type="submit" className="btn-primary btn-replay-submit">
                      Replay from here ⚔
                    </button>
                  </form>
                </div>
              </div>
            </div>
          ) : (
            <div className="empty-selection-prompt">
              {isDetailLoading ? (
                <span className="spinner" />
              ) : (
                <p>Select a node from the story tree to inspect details and fork an alternate timeline.</p>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
