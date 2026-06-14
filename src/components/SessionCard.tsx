import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import * as LucideIcons from 'lucide-react';
import { Clock, Trash2, Edit3 } from 'lucide-react';
import type { Session } from '@/types';
import { useStore } from '@/store/useStore';

interface SessionCardProps {
  session: Session;
  notebookId: string;
}

export default function SessionCard({ session, notebookId }: SessionCardProps) {
  const navigate = useNavigate();
  const { removeSession, openDialog } = useStore();
  const IconComponent = LucideIcons[session.icon as keyof typeof LucideIcons] as React.ElementType || LucideIcons.FileText;

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm(`确定要删除"${session.title}"吗？`)) {
      try {
        await removeSession(notebookId, session.id);
        toast.success('课次已删除');
      } catch (error) {
        toast.error('删除失败，请稍后重试');
      }
    }
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    openDialog('session', notebookId, undefined, session);
  };

  return (
    <div
      onClick={() => navigate(`/subject/${notebookId}/session/${session.id}`)}
      className="group relative bg-white dark:bg-slate-800 rounded-2xl border border-slate-200/80 dark:border-slate-700/80 shadow-sm hover:shadow-xl transition-all duration-300 cursor-pointer overflow-hidden hover:-translate-y-1"
    >
      {/* 操作按钮 — always visible on touch, hover on desktop */}
      <div className="absolute top-3 right-3 flex items-center gap-1 z-10">
        <button
          onClick={handleEdit}
          className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 hover:text-blue-500 hover:bg-blue-50 transition-all"
          title="编辑课次"
        >
          <Edit3 className="w-4 h-4" />
        </button>
        <button
          onClick={handleDelete}
          className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 hover:text-red-500 hover:bg-red-50 transition-all"
          title="删除课次"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* 顶部装饰条 */}
      <div className="h-1 bg-gradient-to-r from-blue-500 to-blue-600" />

      <div className="p-6">
        {/* 图标和标题 */}
        <div className="flex items-start gap-3 mb-4">
          <div className="p-3 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 text-white flex-shrink-0 shadow-md shadow-blue-200 group-hover:shadow-lg group-hover:shadow-blue-300 transition-all">
            <IconComponent className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0 pt-0.5">
            <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200 group-hover:text-blue-600 transition-colors truncate">
              {session.title}
            </h3>
          </div>
        </div>

        {/* 底部信息 */}
        <div className="flex items-center justify-between text-xs text-slate-400 dark:text-slate-500 pt-4 border-t border-slate-100 dark:border-slate-700">
          <span className="flex items-center gap-1.5">
            <LucideIcons.Calendar className="w-3.5 h-3.5" />
            {session.date}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            {session.duration}
          </span>
        </div>
      </div>
    </div>
  );
}
