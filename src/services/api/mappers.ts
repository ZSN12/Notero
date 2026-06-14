import type { Notebook, Session } from '@/types';
import { colorMap, hashStringToInt, iconMap } from './core';
import type { BackendNotebook, BackendSession } from './types';

export function mapBackendNotebook(bn: BackendNotebook): Notebook {
  const fallbackColor = colorMap[hashStringToInt(bn.id) % 6];
  return {
    id: bn.id,
    title: bn.title,
    description: bn.description || '',
    icon: iconMap[bn.icon || ''] || 'BookOpen',
    color: bn.color || fallbackColor,
    sessionCount: bn.session_count,
    updatedAt: bn.created_at.split('T')[0],
    createdAt: bn.created_at.split('T')[0],
  };
}

export function mapBackendSession(bs: BackendSession): Session {
  return {
    id: bs.id,
    notebookId: bs.notebook_id,
    title: bs.title,
    keywords: bs.keywords || [],
    icon: 'FileText',
    date: bs.created_at.split('T')[0],
    duration: '00:00:00',
    content: `# ${bs.title}\n\n在这里开始编写笔记...`,
  };
}
