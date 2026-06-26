import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { useStore } from '@/store/useStore';

export default function CreateDialog() {
  const { dialog, closeDialog, createNotebook, createSession, updateNotebook } = useStore();
  const [title, setTitle] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  const isEditMode = dialog.type === 'notebook' && !!dialog.editingNotebook;

  useEffect(() => {
    if (isEditMode && dialog.editingNotebook) {
      setTitle(dialog.editingNotebook.title);
    } else {
      setTitle('');
    }
  }, [isEditMode, dialog.editingNotebook]);

  if (!dialog.isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;

    setIsSubmitting(true);
    try {
      if (isEditMode && dialog.editingNotebook) {
        await updateNotebook(dialog.editingNotebook.id, title);
      } else if (dialog.type === 'notebook') {
        await createNotebook(title);
      } else if (dialog.type === 'session' && dialog.notebookId) {
        await createSession(dialog.notebookId, title);
      }
      setTitle('');
      closeDialog();
    } catch (error) {
      console.error('[CreateDialog] Submit failed:', error);
      setFormError(isEditMode ? '更新失败，请稍后重试' : '创建失败，请稍后重试');
    } finally {
      setIsSubmitting(false);
    }
  };

  const titleText = isEditMode ? '编辑学科名称' : (dialog.type === 'notebook' ? '新建学科笔记本' : '新建课次');
  const placeholder = isEditMode ? '请输入新的学科名称' : (dialog.type === 'notebook' ? '请输入学科名称，例如"线性代数"' : '请输入课次名称，例如"第一章：行列式"');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={closeDialog} />

      <div className="relative bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6">
        <button
          onClick={closeDialog}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          disabled={isSubmitting}
        >
          <X className="w-4 h-4" />
        </button>

        <h2 className="text-xl font-semibold text-slate-800 dark:text-slate-100 mb-1">{titleText}</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-5">{isEditMode ? '修改后，该学科下所有课次名称将保持不变。' : '取一个清晰的名字，方便后续管理内容。'}</p>

        <form onSubmit={handleSubmit}>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={placeholder}
            className="w-full px-4 py-3 rounded-xl border border-slate-200 dark:border-slate-700 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all text-slate-800 dark:text-slate-100 placeholder:text-slate-400 bg-white dark:bg-slate-900"
            autoFocus
            disabled={isSubmitting}
          />
          {formError && (
            <p className="mt-2 text-sm text-red-600 dark:text-red-400">{formError}</p>
          )}

          <div className="flex gap-3 mt-5">
            <button
              type="button"
              onClick={closeDialog}
              className="flex-1 px-4 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors font-medium"
              disabled={isSubmitting}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!title.trim() || isSubmitting}
              className="flex-1 px-4 py-2.5 rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
            >
              {isSubmitting ? (isEditMode ? '更新中...' : '创建中...') : (isEditMode ? '更新' : '创建')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
