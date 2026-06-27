import { toast } from "sonner";
import { useState } from 'react';
import { downloadTranscriptPDF, exportNotebook, getMediaUrl } from '@/services/api';
import type { NoteLayoutBlock } from '@/lib/noteLayout';

interface Session {
  id?: string;
  title: string;
  duration?: string;
}

interface Notebook {
  id?: string;
  title: string;
}

export function useExport(session: Session | undefined | null, notebook: Notebook | undefined | null) {
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [isExportingPackage, setIsExportingPackage] = useState(false);

  const exportMarkdown = (
    transcriptText: string,
    notes: Array<{ type: string; content: string }>,
    layoutBlocks?: NoteLayoutBlock[],
  ) => {
    if (!session || !notebook) return;
    let md = `# ${session.title}\n\n> 所属科目：${notebook.title}\n`;
    if (session.duration) md += `> 课程时长：${session.duration}\n`;
    md += `> 导出时间：${new Date().toLocaleString('zh-CN')}\n\n`;

    if (layoutBlocks && layoutBlocks.length > 0) {
      // Export using layout blocks order
      for (const block of layoutBlocks) {
        switch (block.type) {
          case 'transcript':
            if (block.content?.trim()) {
              md += `${block.content.trim()}\n\n`;
            }
            break;
          case 'ppt':
            if (block.src) {
              const imgSrc = block.src.startsWith('data:') ? block.src : getMediaUrl(block.src);
              md += `![PPT 第 ${block.page || '?'} 页${block.title ? ' · ' + block.title : ''}](${imgSrc})\n\n`;
            }
            break;
          case 'note':
            if (block.content?.trim()) {
              md += `## 随堂笔记\n\n${block.content.trim()}\n\n`;
            }
            break;
        }
      }
    } else {
      // Fallback: old-style export
      md += `## 语音转文字\n\n${transcriptText.trim()}\n\n---\n\n`;
      if (notes.some(n => n.content.trim())) {
        md += `## 随堂笔记\n\n`;
        notes.filter(n => n.content.trim()).forEach((note, idx) => md += `### 笔记 ${idx + 1}\n\n${note.content}\n\n`);
      }
    }

    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${session.title}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setShowExportMenu(false);
  };

  const exportPDF = async (
    transcriptText: string,
    _notes: Array<{ type: string; content: string }>,
    layoutBlocks?: NoteLayoutBlock[],
  ) => {
    if (!session || !notebook) return;
    setIsExportingPDF(true);
    try {
      if (!session.id) {
        toast.error('没有可导出的转写内容');
        return;
      }

      const hasLocalTranscript = layoutBlocks && layoutBlocks.length > 0
        ? layoutBlocks.some((block) => block.type === 'transcript' && block.content?.trim())
        : transcriptText.trim().length > 0;
      if (!hasLocalTranscript) {
        toast.error('没有可导出的转写内容');
        return;
      }

      const blob = await downloadTranscriptPDF(session.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${session.title}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (err) {
      console.error('PDF export failed:', err);
      toast.error(err instanceof Error ? err.message : '导出 PDF 失败');
    } finally {
      setIsExportingPDF(false);
      setShowExportMenu(false);
    }
  };

  const exportNotebookPackage = async () => {
    if (!notebook?.id) return;
    setIsExportingPackage(true);
    try {
      const pkg = await exportNotebook(notebook.id);
      const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${notebook.title}.notero`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (err: unknown) {
      console.error('Notebook package export failed:', err);
      toast.error(err instanceof Error ? err.message : '导出失败');
    } finally {
      setIsExportingPackage(false);
      setShowExportMenu(false);
    }
  };

  return {
    state: {
      showExportMenu,
      isExportingPDF,
      isExportingPackage,
    },
    actions: {
      setShowExportMenu,
      exportMarkdown,
      exportPDF,
      exportNotebookPackage,
    },
  };
}
