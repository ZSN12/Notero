import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Search, Share2, Download } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { getProfile, getAvatarUrl, type UserProfile } from '@/services/auth';
import SessionCard from '@/components/SessionCard';
import CreateDialog from '@/components/CreateDialog';
import ThemeToggle from '@/components/ThemeToggle';

export default function ChapterList() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { notebooks, sessions, loading, error, openDialog, loadSessions } = useStore();
  const [searchQuery, setSearchQuery] = useState('');
  const [copyFeedback, setCopyFeedback] = useState('');
  const [profile, setProfile] = useState<UserProfile | null>(null);

  const notebook = notebooks.find((n) => n.id === id);
  const notebookSessions = sessions.filter((s) => s.notebookId === id);

  useEffect(() => {
    if (id) {
      loadSessions(id);
      getProfile().then(setProfile).catch(() => {});
    }
  }, [id, loadSessions]);

  const filteredSessions = notebookSessions.filter(s =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handleShare = () => {
    const shareUrl = `${window.location.origin}/subject/${id}`;
    navigator.clipboard.writeText(shareUrl).then(() => {
      setCopyFeedback('已复制');
      setTimeout(() => setCopyFeedback(''), 2000);
    });
  };

  const handleCopyAll = () => {
    const content = notebookSessions.map(s => `# ${s.title}\n${s.summary}`).join('\n\n');
    navigator.clipboard.writeText(content).then(() => {
      setCopyFeedback('已复制');
      setTimeout(() => setCopyFeedback(''), 2000);
    });
  };

  const handleDownload = () => {
    if (!notebook) return;
    const content = notebookSessions.map(s => `# ${s.title}\n${s.summary}`).join('\n\n');
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${notebook.title}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };

  if (!notebook) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-slate-500 dark:text-slate-400">笔记本不存在</p>
        <button onClick={() => navigate('/')} className="px-4 py-2 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors">返回首页</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100">
      <CreateDialog />

      {/* 顶部导航 */}
      <nav className="sticky top-0 z-40 backdrop-blur-xl bg-white/70 border-b border-slate-200/60">
        <div className="max-w-7xl mx-auto px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate('/')}
                className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <ArrowLeft className="w-5 h-5" />
              </button>
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <button onClick={() => navigate('/')} className="min-h-[44px] px-2 flex items-center hover:text-slate-700 transition-colors">
                  首页
                </button>
                <span className="text-slate-300">/</span>
                <span className="text-slate-700 font-medium">{notebook.title}</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <ThemeToggle />
              <div className="hidden sm:flex items-center px-3 py-2 min-h-[44px] bg-slate-100 rounded-lg dark:bg-slate-800">
                <Search className="w-5 h-5 text-slate-400 mr-2" />
                <input
                  type="text"
                  placeholder="搜索课次..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="bg-transparent text-base text-slate-700 dark:text-slate-200 placeholder:text-slate-400 outline-none w-40"
                />
              </div>
              <button onClick={handleShare} className="min-w-[44px] min-h-[44px] rounded-lg text-slate-500 hover:bg-slate-100 flex items-center justify-center transition-colors" title="复制链接">
                <Share2 className="w-4 h-4" />
              </button>
              <button onClick={handleDownload} className="min-w-[44px] min-h-[44px] rounded-lg text-slate-500 hover:bg-slate-100 flex items-center justify-center transition-colors" title="下载全部">
                <Download className="w-4 h-4" />
              </button>
              {copyFeedback && <span className="text-xs text-green-500 font-medium">{copyFeedback}</span>}
              <button onClick={() => navigate('/profile')} className="cursor-pointer">
                {profile?.avatar_url ? (
                  <img src={getAvatarUrl(profile.id)} alt="avatar" className="w-7 h-7 rounded-full object-cover" />
                ) : (
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-white text-xs font-medium">
                    {(profile?.username || profile?.email || 'U')[0].toUpperCase()}
                  </div>
                )}
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* 主内容区 */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-6">
          <h2 className="text-2xl font-bold text-slate-800">
            {notebook.title}
          </h2>
        </div>

        {loading && (
          <div className="text-center py-12">
            <p className="text-slate-400">加载中...</p>
          </div>
        )}

        {error && (
          <div className="text-center py-12">
            <p className="text-red-500">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {notebookSessions.map((session) => (
              <SessionCard key={session.id} session={session} notebookId={notebook.id} />
            ))}

            {/* 新建课次卡片 */}
            <button
              onClick={() => openDialog('session', notebook.id)}
              className="group flex flex-col items-center justify-center min-h-[200px] rounded-2xl border border-slate-200 bg-slate-50/80 hover:bg-slate-50 hover:border-blue-300 transition-all duration-300 cursor-pointer"
            >
              <div className="p-4 rounded-full bg-slate-100 group-hover:bg-blue-50 mb-3 transition-colors">
                <Plus className="w-6 h-6 text-slate-400 group-hover:text-blue-500 transition-colors" />
              </div>
              <span className="text-sm font-medium text-slate-500 group-hover:text-blue-600 transition-colors">
                新建课次
              </span>
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
