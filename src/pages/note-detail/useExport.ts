import { toast } from "sonner";
import { useState } from 'react';
import DOMPurify from 'dompurify';
import { exportNotebook, getMediaUrl } from '@/services/api';
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
    notes: Array<{ type: string; content: string }>,
    layoutBlocks?: NoteLayoutBlock[],
  ) => {
    if (!session || !notebook) return;
    setIsExportingPDF(true);
    try {
      const html2pdf = (await import('html2pdf.js')).default;
      let bodyHtml = '';

      const sanitize = (html: string) => DOMPurify.sanitize(html, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
      if (layoutBlocks && layoutBlocks.length > 0) {
        // Export using layout blocks order
        for (const block of layoutBlocks) {
          switch (block.type) {
            case 'transcript':
              if (block.content?.trim()) {
                bodyHtml += `<div style="margin-bottom:12px;line-height:1.8">${sanitize(block.content.trim())}</div>`;
              }
              break;
            case 'ppt':
              if (block.src) {
                const imgSrc = block.src.startsWith('data:') ? block.src : getMediaUrl(block.src);
                bodyHtml += `<div style="margin-bottom:16px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">`;
                bodyHtml += `<div style="padding:8px 12px;background:#f8fafc;font-size:11px;color:#64748b">PPT 第 ${block.page || '?'} 页${block.title ? ' · ' + block.title : ''}</div>`;
                bodyHtml += `<img src="${imgSrc}" style="width:100%;max-height:400px;object-fit:contain" />`;
                bodyHtml += `</div>`;
              }
              break;
            case 'note':
              if (block.content?.trim()) {
                bodyHtml += `<div style="margin-bottom:16px;padding:12px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px">`;
                bodyHtml += `<h4 style="margin:0 0 8px;color:#92400e;font-size:12px">随堂笔记</h4>`;
                bodyHtml += `<div style="line-height:1.8">${sanitize(block.content.trim())}</div>`;
                bodyHtml += `</div>`;
              }
              break;
          }
        }
      } else {
        // Fallback: old-style export
        bodyHtml += `<div style="white-space:pre-wrap;line-height:1.7">${sanitize(transcriptText.trim())}</div>`;
        if (notes.some(n => n.content.trim())) {
          const notesHtml = notes.filter(n => n.content.trim()).map((n, i) =>
            `<div style="margin-bottom:12px"><h4 style="color:#475569;margin:0 0 4px">笔记 ${i + 1}</h4><div>${sanitize(n.content)}</div></div>`
          ).join('');
          bodyHtml += `<h2 style="font-size:16px;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin:20px 0 12px;color:#1e293b">📖 随堂笔记</h2>${notesHtml}`;
        }
      }

      const container = document.createElement('div');
      container.style.position = 'absolute';
      container.style.left = '-9999px';
      container.style.width = '210mm';
      container.style.padding = '15mm';
      container.style.fontFamily = '"Microsoft YaHei","PingFang SC",sans-serif';
      container.style.fontSize = '13px';
      container.style.color = '#334155';
      container.style.lineHeight = '1.7';
      container.innerHTML = `
        <h1 style="font-size:22px;margin-bottom:6px;color:#1e293b">${session.title}</h1>
        <p style="color:#94a3b8;margin:0 0 16px;font-size:12px">
          ${notebook.title} &nbsp;|&nbsp; 时长 ${session.duration || '-'} &nbsp;|&nbsp; ${new Date().toLocaleString('zh-CN')}
        </p>
        <h2 style="font-size:16px;border-bottom:2px solid #e2e8f0;padding-bottom:6px;margin:20px 0 12px;color:#1e293b">📝 课堂记录</h2>
        ${bodyHtml}
      `;
      document.body.appendChild(container);

      await html2pdf().set({
        margin: 0,
        filename: `${session.title}.pdf`,
        image: { type: 'jpeg', quality: 0.95 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      }).from(container).save();

      document.body.removeChild(container);
    } catch (err) {
      console.error('PDF export failed:', err);
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
