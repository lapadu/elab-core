import React, { useMemo } from 'react';
import { SYSTEM_COLORS } from '../../utils/Shared.jsx';

/**
 * DispatchFlowView – renders a live flow chart of the current dispatcher
 * configuration. Role classification is connection-based: a node is a source
 * if it feeds other nodes, a sink if it consumes, and a processor if both.
 * TRIGGER nodes are shown as a separate row below.
 *
 * Props: { slots } – the current slot state from App.
 */
export default function DispatchFlowView({ slots }) {
  const { nodes, edges } = useMemo(() => buildGraph(slots), [slots]);

  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        Keine aktiven Tasks im Dispatcher.
      </div>
    );
  }

  // Separate triggers from main flow
  const triggers = nodes.filter((n) => n.type === 'TRIGGER');
  const flowNodes = nodes.filter((n) => n.type !== 'TRIGGER');

  // Layout: categorize into columns by connection-based role
  const sources = flowNodes.filter((n) => n.role === 'source');
  const processors = flowNodes.filter((n) => n.role === 'processor');
  const sinks = flowNodes.filter((n) => n.role === 'sink');

  const columns = [sources, processors, sinks].filter((c) => c.length > 0);

  const NODE_W = 200;
  const NODE_H = 60;
  const COL_GAP = 130;
  const ROW_GAP = 20;
  const TRIGGER_Y_OFFSET = 28;

  // Assign positions
  const positions = new Map();
  let totalWidth = 0;

  columns.forEach((col, colIdx) => {
    const colX = colIdx * (NODE_W + COL_GAP) + 40;
    col.forEach((node, rowIdx) => {
      const y = rowIdx * (NODE_H + ROW_GAP) + 40;
      positions.set(node.id, { x: colX, y });
    });
    totalWidth = colX + NODE_W + 40;
  });

  const maxFlowHeight = columns.length > 0
    ? Math.max(...columns.map((c) => c.length * NODE_H + (c.length - 1) * ROW_GAP))
    : 0;

  // Center columns vertically
  columns.forEach((col) => {
    const colHeight = col.length * NODE_H + (col.length - 1) * ROW_GAP;
    const offset = (maxFlowHeight - colHeight) / 2;
    col.forEach((node) => {
      const pos = positions.get(node.id);
      pos.y += offset;
    });
  });

  // Place trigger nodes below the main flow
  const triggerY = maxFlowHeight + 40 + TRIGGER_Y_OFFSET;
  const triggerStartX = 40;
  triggers.forEach((node, idx) => {
    positions.set(node.id, {
      x: triggerStartX + idx * (NODE_W + 24),
      y: triggerY,
    });
  });

  const triggerRowWidth = triggers.length > 0
    ? triggerStartX + triggers.length * (NODE_W + 24)
    : 0;
  const svgWidth = Math.max(totalWidth, triggerRowWidth, 400);
  const svgHeight = triggers.length > 0
    ? triggerY + NODE_H + 40
    : maxFlowHeight + 120;

  const ROLE_STYLES = {
    source: 'border-emerald-600 bg-emerald-950/60',
    processor: 'border-amber-600 bg-amber-950/60',
    sink: 'border-sky-600 bg-sky-950/60',
    trigger: 'border-yellow-600 bg-yellow-950/60',
  };

  const TYPE_BADGE = {
    SENSOR: 'bg-emerald-900 text-emerald-300',
    GENERATOR: 'bg-cyan-900 text-cyan-300',
    ACTUATOR: 'bg-blue-900 text-blue-300',
    MATH: 'bg-purple-900 text-purple-300',
    MEASURE: 'bg-orange-900 text-orange-300',
    CONTROL: 'bg-rose-900 text-rose-300',
    TRIGGER: 'bg-yellow-900 text-yellow-300',
  };

  return (
    <div className="w-full h-full overflow-auto custom-scrollbar p-4">
      <svg
        width={svgWidth}
        height={svgHeight}
        className="mx-auto"
        style={{ minWidth: svgWidth }}
      >
        <defs>
          <marker
            id="flow-arrow"
            markerWidth="8"
            markerHeight="6"
            refX="8"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 8 3, 0 6" fill={SYSTEM_COLORS.text.muted} />
          </marker>
        </defs>

        {/* Trigger divider line */}
        {triggers.length > 0 && (
          <>
            <line
              x1="20" y1={triggerY - 14}
              x2={svgWidth - 20} y2={triggerY - 14}
              stroke={SYSTEM_COLORS.surface.subtle} strokeWidth="1" strokeDasharray="4 4"
            />
            <text x="24" y={triggerY - 20} fill={SYSTEM_COLORS.border.default} fontSize="9" fontFamily="monospace">
              TRIGGER
            </text>
          </>
        )}

        {/* Edges */}
        {edges.map((edge, idx) => {
          const from = positions.get(edge.from);
          const to = positions.get(edge.to);
          if (!from || !to) return null;

          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          const cx = (x1 + x2) / 2;

          return (
            <path
              key={idx}
              d={`M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`}
              fill="none"
              stroke={edge.color || SYSTEM_COLORS.border.default}
              strokeWidth="2"
              markerEnd="url(#flow-arrow)"
              className="transition-all duration-300"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const style = node.type === 'TRIGGER'
            ? ROLE_STYLES.trigger
            : (ROLE_STYLES[node.role] || 'border-slate-600 bg-slate-900');
          const badge = TYPE_BADGE[node.type] || 'bg-slate-800 text-slate-400';

          return (
            <foreignObject
              key={node.id}
              x={pos.x}
              y={pos.y}
              width={NODE_W}
              height={NODE_H}
            >
              <div
                className={`h-full rounded-lg border-2 px-3 py-2 flex flex-col justify-center ${style}`}
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: node.color || SYSTEM_COLORS.text.muted }}
                  />
                  <span className="text-[11px] font-semibold text-slate-100 truncate">
                    {node.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`text-[8px] uppercase font-mono px-1.5 py-0.5 rounded ${badge}`}>
                    {node.type}
                  </span>
                  <span className="text-[9px] text-slate-600">
                    Slot {node.slot}
                  </span>
                  {node.role === 'processor' && (
                    <span className="text-[8px] text-amber-500">⇄</span>
                  )}
                </div>
              </div>
            </foreignObject>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-4 justify-center text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border-2 border-emerald-600 bg-emerald-950/60 inline-block" />
          Quelle
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border-2 border-amber-600 bg-amber-950/60 inline-block" />
          Quelle + Senke
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border-2 border-sky-600 bg-sky-950/60 inline-block" />
          Senke
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-3 rounded border-2 border-yellow-600 bg-yellow-950/60 inline-block" />
          Trigger
        </span>
      </div>
    </div>
  );
}

/**
 * Build a directed graph from the current slot state.
 * Role classification is purely connection-based:
 * - source: node has outgoing edges but no incoming
 * - sink: node has incoming edges but no outgoing
 * - processor: node has both incoming and outgoing edges
 * - source (fallback): isolated node (no edges)
 */
function buildGraph(slots) {
  const nodes = [];
  const edges = [];
  const taskSlotMap = new Map(); // taskId -> nodeId

  // 1. Collect all active tasks (including triggers)
  for (const [slotIdx, task] of Object.entries(slots)) {
    if (!task) continue;
    const taskId = task.originalId || task.id;
    const nodeId = `slot_${slotIdx}`;
    taskSlotMap.set(taskId, nodeId);
    taskSlotMap.set(task.id, nodeId);

    nodes.push({
      id: nodeId,
      taskId,
      slot: slotIdx,
      name: task.name || taskId,
      type: (task.type || 'SENSOR').toUpperCase(),
      color: task.color,
      role: 'source', // initial, will be reclassified below
    });
  }

  // 2. Build edges from input connections
  const hasIncoming = new Set();
  const hasOutgoing = new Set();

  for (const [slotIdx, task] of Object.entries(slots)) {
    if (!task) continue;
    const targetNodeId = `slot_${slotIdx}`;

    // Primary input source
    if (task.inputs?.source) {
      const sourceId = task.inputs.source.originalId || task.inputs.source.id;
      const sourceNodeId = taskSlotMap.get(sourceId);
      if (sourceNodeId !== undefined) {
        edges.push({
          from: sourceNodeId,
          to: targetNodeId,
          color: task.inputs.source.color || SYSTEM_COLORS.border.default,
        });
        hasOutgoing.add(sourceNodeId);
        hasIncoming.add(targetNodeId);
      }
    }

    // Extra channels (multiple inputs)
    if (Array.isArray(task.extraChannels)) {
      for (const ch of task.extraChannels) {
        if (!ch) continue;
        const chId = ch.originalId || ch.id;
        const chNodeId = taskSlotMap.get(chId);
        if (chNodeId !== undefined) {
          edges.push({
            from: chNodeId,
            to: targetNodeId,
            color: ch.color || SYSTEM_COLORS.border.default,
          });
          hasOutgoing.add(chNodeId);
          hasIncoming.add(targetNodeId);
        }
      }
    }
  }

  // 3. Classify roles based on actual connections
  for (const node of nodes) {
    if (node.type === 'TRIGGER') {
      node.role = 'trigger';
      continue;
    }
    const isSource = hasOutgoing.has(node.id);
    const isSink = hasIncoming.has(node.id);
    if (isSource && isSink) node.role = 'processor';
    else if (isSink) node.role = 'sink';
    else node.role = 'source'; // isolated or pure source
  }

  return { nodes, edges };
}
