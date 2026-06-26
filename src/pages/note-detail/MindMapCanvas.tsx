import { useCallback, useEffect, useRef } from 'react';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Node,
  type Edge,
  type NodeProps,
  type NodeChange,
  Handle,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { BookOpen, FileText, Presentation, ArrowRight } from 'lucide-react';
import type { MindMapNode, MindMapData } from '@/services/api';
import { saveMindMapPositions } from '@/services/api';
import ELK from 'elkjs/lib/elk.bundled.js';

// ── Type accents (subtle left-border) ──
const TYPE_ACCENT: Record<string, string> = {
  topic:      'border-l-purple-400',
  concept:    'border-l-blue-400',
  key_point:  'border-l-emerald-400',
  difficulty: 'border-l-rose-400',
  example:    'border-l-amber-400',
  process:    'border-l-cyan-400',
  function:   'border-l-teal-400',
  question:   'border-l-orange-400',
  conclusion: 'border-l-slate-400',
};

const TYPE_LABELS: Record<string, string> = {
  topic: '主题', concept: '概念', key_point: '要点',
  difficulty: '难点', example: '示例', process: '流程',
  function: '函数', question: '问题', conclusion: '结论',
};

const TYPE_BADGE: Record<string, string> = {
  topic:      'bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-300',
  concept:    'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-300',
  key_point:  'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-300',
  difficulty: 'bg-rose-50 text-rose-600 dark:bg-rose-900/20 dark:text-rose-300',
  example:    'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-300',
  process:    'bg-cyan-50 text-cyan-600 dark:bg-cyan-900/20 dark:text-cyan-300',
  function:   'bg-teal-50 text-teal-600 dark:bg-teal-900/20 dark:text-teal-300',
  question:   'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-300',
  conclusion: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

// ── Custom node component ──
function MindMapCardNode({ id, data, selected }: NodeProps) {
  const nodeData = data as unknown as {
    label: string;
    nodeType: string;
    importance: string;
    isRoot: boolean;
  };

  const accent = TYPE_ACCENT[nodeData.nodeType] || TYPE_ACCENT.conclusion;
  const isRoot = id === '__session_root__' || nodeData.isRoot;
  const cardClassName = isRoot
    ? 'px-5 py-3 border-slate-800 dark:border-slate-600 bg-slate-800 dark:bg-slate-700 text-white shadow-lg'
    : `px-3.5 py-2.5 border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 border-l-[3px] ${accent} shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-500`;

  return (
    <div
      className={`
        relative rounded-xl border
        transition-all cursor-pointer group
        ${cardClassName}
        ${selected ? 'ring-2 ring-blue-400 shadow-md' : ''}
      `}
    >
      {!isRoot && <Handle type="target" position={Position.Left} className="!w-1.5 !h-1.5 !bg-slate-300 !border-0" />}

      {!isRoot && nodeData.importance === 'high' && (
        <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-red-400 ring-2 ring-white dark:ring-slate-800" />
      )}

      <div className="flex items-center gap-1.5">
        <span
          className={`
            line-clamp-2 max-w-[220px]
            ${isRoot ? 'text-base font-semibold text-white' : 'text-sm font-medium text-slate-700 dark:text-slate-200'}
          `}
          title={nodeData.label}
        >
          {nodeData.label}
        </span>
      </div>

      <Handle type="source" position={Position.Right} className="!w-1.5 !h-1.5 !bg-slate-300 !border-0" />
    </div>
  );
}

const nodeTypes = { mindMapCard: MindMapCardNode };

// ── ELK Layout ──
const elk = new ELK();

function estimateNodeSize(title: string, isRoot: boolean): { w: number; h: number } {
  const safeTitle = title || '';
  const charWidth = isRoot ? 14 : 11;
  const padding = isRoot ? 60 : 44;
  const w = Math.max(120, Math.min(260, safeTitle.length * charWidth + padding));
  const h = isRoot ? 48 : 40;
  return { w, h };
}

function flattenNodes(nodes: MindMapNode[] | undefined, result: MindMapNode[] = []): MindMapNode[] {
  if (!nodes) return result;
  for (const n of nodes) {
    result.push(n);
    if (n.children) flattenNodes(n.children, result);
  }
  return result;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function buildElkGraph(
  data: MindMapData,
  rootTitle: string,
): { graph: any } {
  const elkNodes: Record<string, unknown>[] = [];
  const rootSize = estimateNodeSize(rootTitle, true);
  elkNodes.push({ id: '__session_root__', width: rootSize.w, height: rootSize.h });

  function addElkNodes(nodes: MindMapNode[] | undefined) {
    if (!nodes) return;
    for (const n of nodes) {
      const size = estimateNodeSize(n.title, false);
      elkNodes.push({ id: n.id, width: size.w, height: size.h });
      if (n.children?.length) {
        addElkNodes(n.children);
      }
    }
  }
  addElkNodes(data.nodes);

  const elkEdges: Record<string, unknown>[] = [];
  function addTreeEdges(nodes: MindMapNode[] | undefined, parentId: string) {
    if (!nodes) return;
    for (const n of nodes) {
      elkEdges.push({ id: `e-${parentId}-${n.id}`, sources: [parentId], targets: [n.id] });
      if (n.children?.length) {
        addTreeEdges(n.children, n.id);
      }
    }
  }
  addTreeEdges(data.nodes, '__session_root__');

  const relations = data.relations || [];
  for (const rel of relations) {
    elkEdges.push({
      id: `rel-${rel.source}-${rel.target}`,
      sources: [rel.source],
      targets: [rel.target],
      labels: [{ text: rel.label }],
    });
  }

  return {
    graph: {
      id: 'graph-root',
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': 'RIGHT',
        'elk.spacing.nodeNode': '40',
        'elk.layered.spacing.nodeNodeBetweenLayers': '90',
        'elk.spacing.componentComponent': '50',
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
        'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
      },
      children: elkNodes,
      edges: elkEdges,
    },
  };
}

async function mindMapToFlow(
  data: MindMapData,
  rootTitle?: string,
): Promise<{ nodes: Node[]; edges: Edge[] }> {
  const resolvedRootTitle = rootTitle?.trim() || data.title?.trim() || '当前课次';
  const { graph } = buildElkGraph(data, resolvedRootTitle);

  const layout = await elk.layout(graph);

  const flowNodes: Node[] = [];
  const flowEdges: Edge[] = [];

  const allNodes = flattenNodes(data.nodes || []);
  const nodeMap = new Map(allNodes.map(n => [n.id, n]));
  nodeMap.set('__session_root__', { id: '__session_root__', title: resolvedRootTitle, type: 'topic', importance: 'high' } as MindMapNode);

  for (const elkNode of layout.children || []) {
    const mmNode = nodeMap.get(elkNode.id);
    if (!mmNode) continue;

    const isRoot = elkNode.id === '__session_root__';

    flowNodes.push({
      id: elkNode.id,
      type: 'mindMapCard',
      position: { x: elkNode.x || 0, y: elkNode.y || 0 },
      data: {
        label: isRoot ? resolvedRootTitle : mmNode.title,
        nodeType: isRoot ? 'topic' : (mmNode.type || 'conclusion'),
        importance: isRoot ? 'high' : (mmNode.importance || 'low'),
        isRoot,
        mindMapNodeId: elkNode.id,
      } as Record<string, unknown>,
    });
  }

  for (const elkEdge of layout.edges || []) {
    const isRelation = elkEdge.id?.startsWith('rel-');

    if (isRelation) {
      flowEdges.push({
        id: elkEdge.id,
        source: elkEdge.sources[0],
        target: elkEdge.targets[0],
        type: 'default',
        style: {
          stroke: '#94a3b8',
          strokeWidth: 1,
          strokeDasharray: '5,5',
          opacity: 0.5,
        },
        label: elkEdge.labels?.[0]?.text || '',
        labelStyle: { fill: '#64748b', fontSize: 10 },
        labelBgStyle: { fill: '#f8fafc', opacity: 0.9 },
        labelBgPadding: [4, 4],
        markerEnd: { type: MarkerType.ArrowClosed, width: 6, height: 6, color: '#94a3b8' },
      });
    } else {
      flowEdges.push({
        id: elkEdge.id,
        source: elkEdge.sources[0],
        target: elkEdge.targets[0],
        type: 'default',
        style: { stroke: '#cbd5e1', strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 10, color: '#cbd5e1' },
      });
    }
  }

  return { nodes: flowNodes, edges: flowEdges };
}

// ── All nodes expanded (folding disabled) ──
function collectAllNodeIds(nodes: MindMapNode[], result = new Set<string>()): Set<string> {
  for (const n of nodes) {
    result.add(n.id);
    if (n.children) collectAllNodeIds(n.children, result);
  }
  return result;
}

function computeDefaultExpanded(nodes: MindMapNode[]): Set<string> {
  return collectAllNodeIds(nodes, new Set<string>(['__session_root__']));
}

// ── Main component ──
interface MindMapCanvasProps {
  data: MindMapData;
  rootTitle?: string;
  sessionId: string;
  onSelect: (node: MindMapNode) => void;
  selectedNode: MindMapNode | null;
  onSourceClick: (source: { source_type: string; page?: number | null; block_id?: string; snippet?: string }) => void;
}

function MindMapCanvasInner({
  data,
  rootTitle,
  sessionId,
  onSelect,
  selectedNode,
  onSourceClick,
}: MindMapCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([] as Edge[]);
  const layoutInProgress = useRef(false);
  const { fitView } = useReactFlow();
  const displayRootTitle = rootTitle?.trim() || data.title?.trim() || '知识导图';

  const runLayout = useCallback(() => {
    if (layoutInProgress.current) return;
    layoutInProgress.current = true;

    mindMapToFlow(data, displayRootTitle)
      .then((result) => {
        const savedPositions = data.positions || {};
        const mergedNodes = result.nodes.map((n) => ({
          ...n,
          position: savedPositions[n.id] || n.position,
        }));
        setNodes(mergedNodes);
        setEdges(result.edges);
        layoutInProgress.current = false;
        setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 50);
      })
      .catch((err) => {
        console.error('ELK layout failed:', err);
        layoutInProgress.current = false;
      });
  }, [data, displayRootTitle, setNodes, setEdges, fitView]);

  useEffect(() => {
    runLayout();
  }, [data, runLayout]);

  const handleSelectNode = useCallback((id: string) => {
    const findNode = (ns: MindMapNode[], targetId: string): MindMapNode | null => {
      for (const n of ns) {
        if (n.id === targetId) return n;
        if (n.children) {
          const found = findNode(n.children, targetId);
          if (found) return found;
        }
      }
      return null;
    };
    const mmNode = id === '__session_root__'
      ? {
          id: '__session_root__',
          title: displayRootTitle,
          description: data.summary || '',
          type: 'topic' as const,
          importance: 'high' as const,
          sources: [],
          children: [],
        }
      : findNode(data.nodes, id);
    if (mmNode) {
      onSelect(mmNode);
    }
  }, [data.nodes, data.summary, displayRootTitle, onSelect]);

  const handleSelectNodeRef = useRef(handleSelectNode);
  handleSelectNodeRef.current = handleSelectNode;

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      handleSelectNodeRef.current(node.id);
    },
    [],
  );

  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    onNodesChange(changes);
    const positionChanges = changes.filter(
      (c): c is Extract<NodeChange, { type: 'position' }> => c.type === 'position'
    );
    if (positionChanges.length > 0) {
            const updated = { ...(data.positions || {}) };
      for (const c of positionChanges) {
        if ('position' in c && c.position) {
          updated[c.id] = c.position;
        }
      }
      data.positions = updated;
      saveMindMapPositions(sessionId, updated).catch((err) => {
        console.error('Failed to save mind map positions:', err);
      });
    }
  }, [onNodesChange, sessionId, data]);

  return (
    <div className="flex h-full">
      {/* Canvas */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={2}
          nodesConnectable={false}
          selectNodesOnDrag={false}
          proOptions={{ hideAttribution: true }}
          className="bg-slate-50/50 dark:bg-slate-900/50"
        >
          <Background color="#e2e8f0" gap={24} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {/* Detail panel */}
      {selectedNode && (
        <div className="w-80 border-l border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 overflow-y-auto flex flex-col">
          {/* Header */}
          <div className="p-4 border-b border-slate-100 dark:border-slate-700">
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${TYPE_BADGE[selectedNode.type] || TYPE_BADGE.conclusion}`}>
                {TYPE_LABELS[selectedNode.type] || selectedNode.type}
              </span>
              {selectedNode.importance && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                  selectedNode.importance === 'high'
                    ? 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400'
                    : selectedNode.importance === 'medium'
                    ? 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400'
                    : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400'
                }`}>
                  {selectedNode.importance === 'high' ? '重要' : selectedNode.importance === 'medium' ? '一般' : '次要'}
                </span>
              )}
            </div>
            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 leading-snug">
              {selectedNode.title}
            </h3>
          </div>

          <div className="p-4 space-y-5">
            {/* Description */}
            {selectedNode.description && (
              <div>
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                  {selectedNode.description}
                </p>
              </div>
            )}

            {/* Related nodes */}
            {data.relations && data.relations.length > 0 && (
              (() => {
                const related = data.relations.filter(
                  r => r.source === selectedNode.id || r.target === selectedNode.id
                );
                if (related.length === 0) return null;

                const allNodes = flattenNodes(data.nodes);
                const nodeMap = new Map(allNodes.map(n => [n.id, n]));

                return (
                  <div>
                    <h4 className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-2">
                      关联节点
                    </h4>
                    <div className="space-y-1.5">
                      {related.map((rel, i) => {
                        const isSource = rel.source === selectedNode.id;
                        const otherId = isSource ? rel.target : rel.source;
                        const otherNode = nodeMap.get(otherId);
                        if (!otherNode) return null;
                        return (
                          <button
                            key={i}
                            onClick={() => handleSelectNode(otherId)}
                            className="w-full flex items-center gap-2 text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-700/30 border border-slate-100 dark:border-slate-700/50 hover:bg-blue-50 dark:hover:bg-blue-900/10 hover:border-blue-200 dark:hover:border-blue-800 transition-colors text-left"
                          >
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${TYPE_BADGE[otherNode.type] || TYPE_BADGE.conclusion}`}>
                              {TYPE_LABELS[otherNode.type] || otherNode.type}
                            </span>
                            <span className="text-slate-700 dark:text-slate-200 flex-1 truncate font-medium">{otherNode.title}</span>
                            <span className="flex items-center gap-0.5 text-slate-400 dark:text-slate-500 text-[10px] shrink-0">
                              {isSource ? (
                                <><span>{rel.label}</span><ArrowRight className="w-3 h-3" /></>
                              ) : (
                                <><ArrowRight className="w-3 h-3 rotate-180" /><span>{rel.label}</span></>
                              )}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })()
            )}

            {/* Sources */}
            {selectedNode.sources && selectedNode.sources.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-2">
                  来源
                </h4>
                <div className="space-y-2">
                  {selectedNode.sources.map((src, i) => (
                    <div
                      key={i}
                      className={`text-xs p-3 rounded-lg border border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-700/30 transition-colors ${
                        src.source_type === 'ppt' && src.page != null
                          ? 'cursor-pointer hover:bg-blue-50/50 dark:hover:bg-blue-900/10 hover:border-blue-200 dark:hover:border-blue-800'
                          : ''
                      }`}
                      onClick={() => onSourceClick(src)}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
                          {src.source_type === 'ppt' ? (
                            <><Presentation className="w-3 h-3" /> PPT</>
                          ) : src.source_type === 'transcript' || src.source_type === 'note' ? (
                            <><FileText className="w-3 h-3" /> 课堂内容</>
                          ) : (
                            <><BookOpen className="w-3 h-3" /> 笔记</>
                          )}
                        </span>
                        {src.page != null && (
                          <span className="text-blue-600 dark:text-blue-400 font-medium">
                            第 {src.page} 页
                          </span>
                        )}
                      </div>
                      <p className="text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-3">
                        {src.snippet}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!selectedNode.description && (!selectedNode.sources || selectedNode.sources.length === 0) && (
              <p className="text-sm text-slate-400 dark:text-slate-500 italic">暂无详细说明</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MindMapCanvas(props: MindMapCanvasProps) {
  return (
    <ReactFlowProvider>
      <MindMapCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

/* eslint-disable react-refresh/only-export-components */
export { computeDefaultExpanded };
