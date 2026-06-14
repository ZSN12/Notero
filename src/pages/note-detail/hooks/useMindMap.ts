import { useState, useEffect, useCallback, useRef } from 'react';
import {
  getSessionMindMap, generateSessionMindMap, deleteSessionMindMap,
} from '@/services/api';
import type { MindMapStatus, MindMapNode, SessionProcessingStatus } from '@/services/api';
import { computeDefaultExpanded } from '../MindMapCanvas';

function deriveMindMapStatus(
  sessionId: string,
  processingStatus: SessionProcessingStatus | null,
): MindMapStatus | null {
  if (!processingStatus) return null;
  const stage = processingStatus.stages.mindmap;
  if (!stage) return null;

  const base: MindMapStatus = {
    session_id: sessionId,
    // 'fallback' means the transcript used local cleanup; the auxiliary material
    // is not necessarily broken, just potentially outdated → show as stale.
    status: stage.status === 'fallback' ? 'stale' : stage.status as MindMapStatus['status'],
    mind_map: null,
    progress: stage.progress,
    error: stage.error_message,
  };

  return base;
}

export function useMindMap(
  sessionId: string | undefined,
  processingStatus: SessionProcessingStatus | null,
) {
  const [showMindMap, setShowMindMap] = useState(false);
  const [mindMapStatus, setMindMapStatus] = useState<MindMapStatus | null>(null);
  const [isGeneratingMindMap, setIsGeneratingMindMap] = useState(false);
  const [selectedMindMapNode, setSelectedMindMapNode] = useState<MindMapNode | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [copyMindMapSuccess, setCopyMindMapSuccess] = useState(false);

  const derivedStatus = deriveMindMapStatus(sessionId || '', processingStatus);
  const fetchedOnErrorRef = useRef(false);

  // When derived status changes, update local status and fetch data if ready or error
  useEffect(() => {
    if (!sessionId || !derivedStatus) return;

    setMindMapStatus(prev => {
      if (!prev) return derivedStatus;
      return { ...prev, status: derivedStatus.status, progress: derivedStatus.progress, error: derivedStatus.error };
    });

    if (derivedStatus.status === 'ready' || derivedStatus.status === 'stale') {
      fetchedOnErrorRef.current = false;
      getSessionMindMap(sessionId).then((data) => {
        setMindMapStatus(data);
        if (data.mind_map?.nodes) {
          setExpandedNodes(computeDefaultExpanded(data.mind_map.nodes));
        }
      }).catch(() => {
        setMindMapStatus(prev => prev ? { ...prev, status: 'error', error: '获取导图数据失败' } : { session_id: sessionId, status: 'error', mind_map: null, error: '获取导图数据失败' });
      });
    } else if (derivedStatus.status === 'error' && !fetchedOnErrorRef.current) {
      fetchedOnErrorRef.current = true;
      getSessionMindMap(sessionId).then((data) => {
        setMindMapStatus(data);
        if (data.mind_map?.nodes) {
          setExpandedNodes(computeDefaultExpanded(data.mind_map.nodes));
        }
      }).catch(() => {
        setMindMapStatus(prev => prev ? { ...prev, status: 'error', error: '获取导图数据失败' } : { session_id: sessionId, status: 'error', mind_map: null, error: '获取导图数据失败' });
      });
    }
  }, [sessionId, derivedStatus?.status, derivedStatus?.progress, derivedStatus?.error]);

  // Auto-trigger when drawer opens and status indicates generation needed
  useEffect(() => {
    if (!sessionId || !showMindMap) return;
    const stage = processingStatus?.stages.mindmap;
    if (!stage) return;

    // Only auto-trigger when no usable output exists. Stale / fallback / error
    // outputs are kept so the user can still view them and choose to regenerate.
    const shouldAutoGenerate = ['idle', 'not_generated', 'empty'].includes(stage.status);
    if (shouldAutoGenerate) {
      handleGenerateMindMap();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, showMindMap, processingStatus?.stages.mindmap?.status]);

  const handleGenerateMindMap = async (force = false) => {
    if (!sessionId) return;
    setIsGeneratingMindMap(true);
    try {
      const result = await generateSessionMindMap(sessionId, force);
      setMindMapStatus(result);
      if (result.status === 'ready' && result.mind_map?.nodes) {
        setExpandedNodes(new Set(result.mind_map.nodes.map(n => n.id)));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '生成失败';
      setMindMapStatus(prev => prev ? { ...prev, status: 'error', error: msg } : { session_id: sessionId, status: 'error', mind_map: null, error: msg });
    } finally {
      setIsGeneratingMindMap(false);
    }
  };

  const handleDeleteMindMap = async () => {
    if (!sessionId || !window.confirm('确定要删除知识导图吗？')) return;
    try {
      await deleteSessionMindMap(sessionId);
      setMindMapStatus({ session_id: sessionId, status: 'not_generated', mind_map: null, error: null });
      setSelectedMindMapNode(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '删除导图失败';
      setMindMapStatus(prev => prev ? { ...prev, status: 'error', error: msg } : { session_id: sessionId, status: 'error', mind_map: null, error: msg });
    }
  };

  const handleCopyMindMapOutline = useCallback(() => {
    if (!mindMapStatus?.mind_map) return;
    const lines: string[] = [];
    const walk = (nodes: MindMapNode[], depth: number) => {
      for (const node of nodes) {
        lines.push('  '.repeat(depth) + '- ' + node.title);
        if (node.children?.length) walk(node.children, depth + 1);
      }
    };
    lines.push('# ' + mindMapStatus.mind_map.title);
    if (mindMapStatus.mind_map.summary) lines.push(mindMapStatus.mind_map.summary);
    walk(mindMapStatus.mind_map.nodes, 0);
    navigator.clipboard.writeText(lines.join('\n')).then(() => { setCopyMindMapSuccess(true); setTimeout(() => setCopyMindMapSuccess(false), 2000); }).catch(() => {
      setMindMapStatus(prev => prev ? { ...prev, error: '复制失败，请检查浏览器剪贴板权限' } : prev);
    });
  }, [mindMapStatus]);

  const toggleNodeExpand = (nodeId: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  };

  return {
    state: { showMindMap, mindMapStatus, isGeneratingMindMap, selectedMindMapNode, expandedNodes, copyMindMapSuccess },
    actions: { setShowMindMap, setSelectedMindMapNode, setExpandedNodes, handleGenerateMindMap, handleDeleteMindMap, handleCopyMindMapOutline, toggleNodeExpand, setMindMapStatus },
  };
}
