import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { getWorldMap } from '../api/client';

// Chapter colour palette — matches the landing page's chapter card accent colours
const CHAPTER_COLORS = {
  1: { fill: '#c9a84c', border: '#e8c06a', label: 'Chapter 1' },
  2: { fill: '#4ab8a0', border: '#6dd4be', label: 'Chapter 2' },
  3: { fill: '#d9614c', border: '#f07860', label: 'Chapter 3' },
  4: { fill: '#9b59b6', border: '#b07dd0', label: 'Chapter 4' },
};

const NODE_RADIUS = 30;
const CANVAS_W = 900;
const CANVAS_H = 600;
const FORCE_ITERS = 80;
const REPULSION = 22000;
const ATTRACTION = 0.04;
const SPRING_LENGTH = 150;
const CENTER_GRAVITY = 0.005;
const DAMPING = 0.82;

/**
 * Spring-repulsion force-directed layout (synchronous, runs in useMemo).
 * Produces stable x,y positions for up to ~30 nodes in < 2ms.
 */
function forceLayout(nodes, edges) {
  if (nodes.length === 0) return {};
  if (nodes.length === 1) {
    return { [nodes[0].id]: { x: CANVAS_W / 2, y: CANVAS_H / 2 } };
  }

  // Circle initialisation — larger radius so nodes start spread out
  const positions = {};
  const velocities = {};
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    positions[n.id] = {
      x: CANVAS_W / 2 + 220 * Math.cos(angle),
      y: CANVAS_H / 2 + 180 * Math.sin(angle),
    };
    velocities[n.id] = { x: 0, y: 0 };
  });

  for (let iter = 0; iter < FORCE_ITERS; iter++) {
    const forces = {};
    nodes.forEach((n) => {
      forces[n.id] = { x: 0, y: 0 };
    });

    // Repulsion between all pairs
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = positions[b.id].x - positions[a.id].x;
        const dy = positions[b.id].y - positions[a.id].y;
        const dist2 = dx * dx + dy * dy || 0.01;
        const dist = Math.sqrt(dist2);
        const force = REPULSION / dist2;
        const fx = (force * dx) / dist;
        const fy = (force * dy) / dist;
        forces[a.id].x -= fx;
        forces[a.id].y -= fy;
        forces[b.id].x += fx;
        forces[b.id].y += fy;
      }
    }

    // Attraction along edges (Hooke's spring with ideal length)
    edges.forEach((e) => {
      const a = positions[e.source_id];
      const b = positions[e.target_id];
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const displacement = dist - SPRING_LENGTH;
      const springForce = ATTRACTION * displacement;
      const fx = springForce * (dx / dist);
      const fy = springForce * (dy / dist);
      forces[e.source_id].x += fx;
      forces[e.source_id].y += fy;
      forces[e.target_id].x -= fx;
      forces[e.target_id].y -= fy;
    });

    // Gentle pull toward center so disconnected or unvisited nodes don't wander off
    nodes.forEach((n) => {
      forces[n.id].x += CENTER_GRAVITY * (CANVAS_W / 2 - positions[n.id].x);
      forces[n.id].y += CENTER_GRAVITY * (CANVAS_H / 2 - positions[n.id].y);
    });

    // Integrate
    nodes.forEach((n) => {
      velocities[n.id].x = (velocities[n.id].x + forces[n.id].x) * DAMPING;
      velocities[n.id].y = (velocities[n.id].y + forces[n.id].y) * DAMPING;
      positions[n.id].x += velocities[n.id].x;
      positions[n.id].y += velocities[n.id].y;

      // Clamp to canvas with padding
      const pad = NODE_RADIUS + 35;
      positions[n.id].x = Math.max(pad, Math.min(CANVAS_W - pad, positions[n.id].x));
      positions[n.id].y = Math.max(pad, Math.min(CANVAS_H - pad, positions[n.id].y));
    });
  }

  return positions;
}

export default function WorldMapScreen({ session, onNavigateToMain }) {
  const [mapData, setMapData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tooltip, setTooltip] = useState(null); // { node, x, y }
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, scale: 1 });
  const svgRef = useRef(null);
  const panRef = useRef(null);

  useEffect(() => {
    if (!session?.id) return;
    let isMounted = true;
    setIsLoading(true);
    setError(null);
    getWorldMap(session.id)
      .then((data) => { if (isMounted) setMapData(data); })
      .catch((err) => { if (isMounted) setError(err.message); })
      .finally(() => { if (isMounted) setIsLoading(false); });
    return () => { isMounted = false; };
  }, [session?.id]);

  // Compute force-directed positions
  const positions = useMemo(() => {
    if (!mapData?.nodes?.length) return {};
    return forceLayout(mapData.nodes, mapData.edges || []);
  }, [mapData]);

  // Pan handlers
  const handlePointerDown = useCallback((e) => {
    if (e.target.closest('.map-node-group')) return; // don't start pan on node
    panRef.current = { startX: e.clientX, startY: e.clientY, startVb: { ...viewBox } };
    e.currentTarget.setPointerCapture(e.pointerId);
  }, [viewBox]);

  const handlePointerMove = useCallback((e) => {
    if (!panRef.current) return;
    const dx = (e.clientX - panRef.current.startX) * viewBox.scale;
    const dy = (e.clientY - panRef.current.startY) * viewBox.scale;
    setViewBox((v) => ({
      ...v,
      x: panRef.current.startVb.x - dx,
      y: panRef.current.startVb.y - dy,
    }));
  }, [viewBox.scale]);

  const handlePointerUp = useCallback(() => { panRef.current = null; }, []);

  // Zoom on wheel
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.15 : 0.87;
    setViewBox((v) => ({
      ...v,
      scale: Math.max(0.3, Math.min(4, v.scale * factor)),
    }));
  }, []);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  const resetView = () => setViewBox({ x: 0, y: 0, scale: 1 });

  const vbWidth = CANVAS_W * viewBox.scale;
  const vbHeight = CANVAS_H * viewBox.scale;
  const vbStr = `${viewBox.x} ${viewBox.y} ${vbWidth} ${vbHeight}`;

  if (isLoading) {
    return (
      <div className="wm-layout">
        <header className="wm-navbar">
          <button className="btn-back-story" onClick={onNavigateToMain}>← Back to Story</button>
          <h2>WORLD MAP</h2>
        </header>
        <div className="wm-loading-overlay"><span className="spinner" /> Loading world map…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="wm-layout">
        <header className="wm-navbar">
          <button className="btn-back-story" onClick={onNavigateToMain}>← Back to Story</button>
          <h2>WORLD MAP</h2>
        </header>
        <div className="graph-error-banner" role="alert">⚠️ {error}</div>
      </div>
    );
  }

  const nodes = mapData?.nodes || [];
  const edges = mapData?.edges || [];
  const currentLocation = mapData?.current_location || '';

  return (
    <div className="wm-layout">
      {/* ── Navbar ── */}
      <header className="wm-navbar">
        <div className="wm-nav-left">
          <button className="btn-back-story" onClick={onNavigateToMain}>← Back to Story</button>
          <div className="graph-title-block">
            <h2>WORLD MAP</h2>
            <span className="graph-node-counter">
              {nodes.filter((n) => n.visited).length} visited ·{' '}
              {nodes.filter((n) => !n.visited).length} mentioned
            </span>
          </div>
        </div>

        {/* Legend */}
        <div className="wm-legend">
          {Object.entries(CHAPTER_COLORS).map(([ch, col]) => (
            <div key={ch} className="wm-legend-item">
              <span className="wm-legend-dot" style={{ background: col.fill }} />
              <span>{col.label}</span>
            </div>
          ))}
          <div className="wm-legend-item">
            <span className="wm-legend-dot wm-legend-mentioned" />
            <span>Mentioned</span>
          </div>
        </div>

        <button className="wm-reset-btn" onClick={resetView}>⊕ Reset View</button>
      </header>

      {/* ── SVG Canvas ── */}
      <div className="wm-canvas-wrapper">
        <svg
          ref={svgRef}
          className="wm-svg"
          viewBox={vbStr}
          width="100%"
          height="100%"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          style={{ cursor: panRef.current ? 'grabbing' : 'grab' }}
        >
          <defs>
            <filter id="wm-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <marker id="wm-arrow" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(255,255,255,0.25)" />
            </marker>
          </defs>

          {/* Edges — only real travel connections */}
          <g className="wm-edges-layer">
            {edges.map((edge) => {
              const src = positions[edge.source_id];
              const tgt = positions[edge.target_id];
              if (!src || !tgt) return null;
              // Shorten line to stop at node circumference
              const dx = tgt.x - src.x;
              const dy = tgt.y - src.y;
              const dist = Math.sqrt(dx * dx + dy * dy) || 1;
              const ux = dx / dist;
              const uy = dy / dist;
              const x1 = src.x + ux * (NODE_RADIUS + 2);
              const y1 = src.y + uy * (NODE_RADIUS + 2);
              const x2 = tgt.x - ux * (NODE_RADIUS + 8);
              const y2 = tgt.y - uy * (NODE_RADIUS + 8);
              return (
                <line
                  key={`${edge.source_id}-${edge.target_id}`}
                  x1={x1} y1={y1} x2={x2} y2={y2}
                  className="wm-edge"
                  markerEnd="url(#wm-arrow)"
                />
              );
            })}
          </g>

          {/* Nodes */}
          <g className="wm-nodes-layer">
            {nodes.map((node) => {
              const pos = positions[node.id];
              if (!pos) return null;
              const chCol = CHAPTER_COLORS[node.chapter_number] || CHAPTER_COLORS[1];
              const isCurrent = node.is_current;
              const isVisited = node.visited;

              return (
                <g
                  key={node.id}
                  className="map-node-group"
                  transform={`translate(${pos.x}, ${pos.y})`}
                  onMouseEnter={(e) => {
                    const rect = svgRef.current?.getBoundingClientRect();
                    setTooltip({
                      node,
                      x: e.clientX - (rect?.left || 0),
                      y: e.clientY - (rect?.top || 0),
                    });
                  }}
                  onMouseLeave={() => setTooltip(null)}
                  style={{ cursor: 'pointer' }}
                >
                  {/* Pulsing ring for current location */}
                  {isCurrent && (
                    <circle
                      r={NODE_RADIUS + 10}
                      className="wm-current-pulse"
                      fill="none"
                      stroke={chCol.border}
                    />
                  )}

                  {/* Node circle */}
                  <circle
                    r={NODE_RADIUS}
                    fill={isVisited ? chCol.fill : 'transparent'}
                    stroke={chCol.border}
                    strokeWidth={isVisited ? 2 : 2}
                    strokeDasharray={isVisited ? 'none' : '6 4'}
                    opacity={isVisited ? 1 : 0.7}
                    filter={isCurrent ? 'url(#wm-glow)' : undefined}
                  />

                  {/* Location name label */}
                  <text
                    textAnchor="middle"
                    dy={NODE_RADIUS + 16}
                    className="wm-node-label"
                    fill={isVisited ? '#e8dcc8' : '#888'}
                  >
                    {node.name.length > 18 ? node.name.slice(0, 17) + '…' : node.name}
                  </text>

                  {/* Icon inside circle */}
                  <text textAnchor="middle" dy="6" fontSize="16">
                    {isCurrent ? '⬡' : isVisited ? '◆' : '◇'}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* Hover Tooltip */}
        {tooltip && (
          <div
            className="wm-tooltip"
            style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}
          >
            <div className="wm-tooltip-name">{tooltip.node.name}</div>
            <div className="wm-tooltip-meta">
              {tooltip.node.visited ? `First reached: Turn ${tooltip.node.visited_at_turn}` : 'Not yet reached'}
              {' · '}Ch.{tooltip.node.chapter_number}
            </div>
            <div className="wm-tooltip-desc">{tooltip.node.description}</div>
          </div>
        )}

        {/* Empty state */}
        {nodes.length === 0 && (
          <div className="wm-empty-state">
            <p>No locations discovered yet. Begin your campaign to build the map.</p>
          </div>
        )}
      </div>
    </div>
  );
}
