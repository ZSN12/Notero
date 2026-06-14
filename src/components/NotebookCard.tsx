import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import * as LucideIcons from 'lucide-react';
import { ArrowRight, Trash2, Edit3, Loader2 } from 'lucide-react';
import type { Notebook } from '@/types';
import { useStore } from '@/store/useStore';

interface NotebookCardProps {
  notebook: Notebook;
}

export default function NotebookCard({ notebook }: NotebookCardProps) {
  const navigate = useNavigate();
  const { removeNotebook, openDialog } = useStore();
  const [isDeleting, setIsDeleting] = useState(false);
  const IconComponent = LucideIcons[notebook.icon as keyof typeof LucideIcons] as React.ElementType || LucideIcons.BookOpen;

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isDeleting) return;
    if (window.confirm(`确定要删除"${notebook.title}"吗？所有课次也会被删除。`)) {
      setIsDeleting(true);
      try {
        await removeNotebook(notebook.id);
        toast.success('笔记本已删除');
      } catch (error) {
        toast.error('删除失败，请稍后重试');
      } finally {
        setIsDeleting(false);
      }
    }
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    openDialog('notebook', undefined, notebook);
  };

  return (
    <div
      onClick={() => navigate(`/subject/${notebook.id}`)}
      className="group relative bg-white dark:bg-slate-800 rounded-2xl border border-slate-200/80 dark:border-slate-700/80 shadow-sm hover:shadow-xl transition-all duration-300 cursor-pointer overflow-hidden hover:-translate-y-1"
    >
      {/* 操作按钮 — always visible on touch, hover on desktop */}
      <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 transition-all z-10">
        <button
          onClick={handleEdit}
          className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-all"
          title="编辑学科"
        >
          <Edit3 className="w-4 h-4" />
        </button>
        <button
          onClick={handleDelete}
          disabled={isDeleting}
          className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          title="删除学科"
        >
          {isDeleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
        </button>
      </div>

      <div className="p-6">
        {/* 图标 */}
        <div className={`p-3 rounded-xl bg-gradient-to-br ${notebook.color} shadow-lg inline-block mb-4`}>
          <IconComponent className="w-6 h-6 text-white" />
        </div>

        <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-2 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
          {notebook.title}
        </h3>

        <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-2 mb-4">
          {notebook.description}
        </p>

        <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 pt-3 border-t border-slate-100 dark:border-slate-700">
          <span>{notebook.sessionCount} 个课次</span>
          <ArrowRight className="w-4 h-4 text-slate-300 group-hover:text-blue-500 group-hover:translate-x-1 transition-all" />
        </div>
      </div>
    </div>
  );
}
