import { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Plus, Search, Upload } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { getProfile, getAvatarUrl } from '@/services/auth';
import { importNotebook } from '@/services/api';
import NotebookCard from '@/components/NotebookCard';
import CreateDialog from '@/components/CreateDialog';
import ThemeToggle from '@/components/ThemeToggle';

export default function Dashboard() {
  const { notebooks, loading, error, openDialog, loadNotebooks } = useStore();
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');
  const [profile, setProfile] = useState<any>(null);
  const [isImporting, setIsImporting] = useState(false);
  const importFileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadNotebooks();
    getProfile().then(setProfile).catch(() => {});
  }, [loadNotebooks]);

  const handleImportClick = () => {
    importFileRef.current?.click();
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.notero')) {
      toast.error('请选择 .notero 文件');
      return;
    }

    setIsImporting(true);
    try {
      const text = await file.text();
      const pkg = JSON.parse(text);
      await importNotebook(pkg);
      toast.success('笔记本导入成功');
      loadNotebooks();
    } catch (err: unknown) {
      console.error('Import failed:', err);
      toast.error(err instanceof Error ? err.message : '导入失败，请检查文件格式');
    } finally {
      setIsImporting(false);
      if (importFileRef.current) importFileRef.current.value = '';
    }
  };

  const filteredNotebooks = notebooks.filter(nb =>
    nb.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    nb.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-100">
      <CreateDialog />

      {/* 顶部导航 */}
      <nav className="sticky top-0 z-40 backdrop-blur-xl bg-white/70 border-b border-slate-200/60">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-bold text-slate-800">AI Notebook</h1>
            </div>

            <div className="flex items-center gap-3">
              <ThemeToggle />
              <div className="hidden md:flex items-center px-3 py-2 min-h-[44px] bg-slate-100 rounded-xl dark:bg-slate-800">
                <Search className="w-5 h-5 text-slate-400 mr-2" />
                <input
                  type="text"
                  placeholder="搜索学科..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="bg-transparent text-base text-slate-700 dark:text-slate-200 placeholder:text-slate-400 outline-none w-48"
                />
              </div>
              <button onClick={() => navigate('/profile')} className="cursor-pointer">
                {profile?.avatar_url ? (
                  <img src={getAvatarUrl(profile.id)} alt="avatar" className="w-8 h-8 rounded-full object-cover" />
                ) : (
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-white text-sm font-medium">
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
          <h2 className="text-2xl font-bold text-slate-800 mb-1">我的笔记本</h2>
          <p className="text-slate-500">按学科分类管理你的学习内容</p>
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
            {notebooks.map((notebook) => (
              <NotebookCard key={notebook.id} notebook={notebook} />
            ))}

            {/* 新建笔记本卡片 */}
            <button
              onClick={() => openDialog('notebook')}
              className="group flex flex-col items-center justify-center min-h-[200px] rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 hover:bg-slate-50 hover:border-blue-300 transition-all duration-300 cursor-pointer"
            >
              <div className="p-4 rounded-full bg-slate-100 group-hover:bg-blue-50 mb-3 transition-colors">
                <Plus className="w-6 h-6 text-slate-400 group-hover:text-blue-500 transition-colors" />
              </div>
              <span className="text-sm font-medium text-slate-500 group-hover:text-blue-600 transition-colors">
                新建学科
              </span>
            </button>

            {/* 导入笔记本卡片 */}
            <button
              onClick={handleImportClick}
              disabled={isImporting}
              className="group flex flex-col items-center justify-center min-h-[200px] rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 hover:bg-slate-50 hover:border-green-300 transition-all duration-300 cursor-pointer disabled:opacity-50"
            >
              <div className="p-4 rounded-full bg-slate-100 group-hover:bg-green-50 mb-3 transition-colors">
                {isImporting ? (
                  <div className="w-6 h-6 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Upload className="w-6 h-6 text-slate-400 group-hover:text-green-500 transition-colors" />
                )}
              </div>
              <span className="text-sm font-medium text-slate-500 group-hover:text-green-600 transition-colors">
                {isImporting ? '导入中...' : '导入笔记本'}
              </span>
            </button>

            <input
              ref={importFileRef}
              type="file"
              accept=".notero"
              onChange={handleImportFile}
              className="hidden"
            />
          </div>
        )}
      </main>
    </div>
  );
}
