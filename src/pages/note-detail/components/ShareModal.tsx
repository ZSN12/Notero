import { X, Loader2 } from 'lucide-react';
import type { useShare } from '@/pages/note-detail/hooks/useShare';

interface ShareModalProps {
  share: ReturnType<typeof useShare>;
  sessionId?: string;
}

export function ShareModal({ share, sessionId }: ShareModalProps) {
  if (!share.state.showShareModal) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={() => share.actions.setShowShareModal(false)}
    >
      <div
        className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl p-6 w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200">分享课次</h3>
          <button
            onClick={() => share.actions.setShowShareModal(false)}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        {share.state.shareLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
          </div>
        ) : share.state.shareEnabled && share.state.shareLink ? (
          <>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-green-400" />
              <span className="text-xs text-green-600 dark:text-green-400">分享已开启</span>
              {share.state.shareExpiresAt && (
                <span className="text-xs text-amber-600 dark:text-amber-400 ml-2">
                  有效期至 {new Date(share.state.shareExpiresAt).toLocaleString()}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mb-4">
              <input
                readOnly
                value={share.state.shareLink}
                className="flex-1 px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-300"
              />
              <button
                onClick={() => {
                  navigator.clipboard.writeText(share.state.shareLink);
                  share.actions.setCopySuccess(true);
                  setTimeout(() => share.actions.setCopySuccess(false), 3000);
                }}
                className="px-3 py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors"
              >
                {share.state.copySuccess ? '已复制' : '复制'}
              </button>
            </div>
            {share.state.shareMaxViews !== null && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                已访问 {share.state.shareViewCount} / {share.state.shareMaxViews} 次
              </p>
            )}
            <button
              onClick={() => share.actions.handleDisableShare(sessionId!)}
              className="w-full py-2 text-sm text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
            >
              关闭分享
            </button>
          </>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">有效期（小时）</label>
                <input
                  type="number"
                  min={1}
                  placeholder="不限"
                  value={share.state.shareExpiresIn}
                  onChange={(e) =>
                    share.actions.setShareExpiresIn(e.target.value === '' ? '' : Number(e.target.value))
                  }
                  className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">最大访问次数</label>
                <input
                  type="number"
                  min={1}
                  placeholder="不限"
                  value={share.state.shareMaxViewsInput}
                  onChange={(e) =>
                    share.actions.setShareMaxViewsInput(e.target.value === '' ? '' : Number(e.target.value))
                  }
                  className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-300"
                />
              </div>
            </div>
            <button
              onClick={() =>
                share.actions.handleShareSession(sessionId!, share.state.shareExpiresIn, share.state.shareMaxViewsInput)
              }
              className="w-full py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors"
            >
              开启分享
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
