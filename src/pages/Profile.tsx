import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { getProfile, updateProfile, changePassword, uploadAvatar, getAvatarUrl, logout, type UserProfile } from "@/services/auth";
import { getToken } from "@/services/auth";
import { User, Lock, LogOut, ArrowLeft, CheckCircle2, AlertCircle, Camera } from "lucide-react";

export default function Profile() {
  const navigate = useNavigate();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const [username, setUsername] = useState("");
  const [saving, setSaving] = useState(false);
  const [usernameMsg, setUsernameMsg] = useState<{ type: string; text: string } | null>(null);

  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [pwdSaving, setPwdSaving] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ type: string; text: string } | null>(null);

  const [avatarUploading, setAvatarUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    (async () => {
      if (!getToken()) { navigate("/login", { replace: true }); return; }
      try {
        const data = await getProfile();
        setProfile(data);
        setUsername(data.username || "");
      } catch {
        logout();
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  const handleSaveUsername = async () => {
    if (username.length < 2) { setUsernameMsg({ type: "error", text: "用户名至少 2 个字符" }); return; }
    setSaving(true);
    setUsernameMsg(null);
    try {
      const updated = await updateProfile(username);
      setProfile(updated);
      setUsernameMsg({ type: "success", text: "用户名已更新" });
    } catch (e: unknown) {
      setUsernameMsg({ type: "error", text: e instanceof Error ? e.message : '更新失败' });
    } finally { setSaving(false); }
  };

  const handleChangePassword = async () => {
    if (newPwd.length < 8) { setPwdMsg({ type: "error", text: "新密码至少 8 个字符" }); return; }
    if (newPwd !== confirmPwd) { setPwdMsg({ type: "error", text: "两次输入的密码不一致" }); return; }
    setPwdSaving(true);
    setPwdMsg(null);
    try {
      await changePassword(oldPwd, newPwd);
      setPwdMsg({ type: "success", text: "密码修改成功" });
      setOldPwd(""); setNewPwd(""); setConfirmPwd("");
    } catch (e: unknown) {
      setPwdMsg({ type: "error", text: e instanceof Error ? e.message : '修改失败' });
    } finally { setPwdSaving(false); }
  };

  const handleUploadAvatar = async (file: File) => {
    setAvatarUploading(true);
    try {
      const url = await uploadAvatar(file);
      setProfile((p) => (p ? { ...p, avatar_url: url } : null));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '上传失败');
    } finally { setAvatarUploading(false); }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" /></div>;
  if (!profile) return null;

  const avatarUrl = profile.avatar_url ? getAvatarUrl(profile.id) : "";

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      {/* Top bar */}
      <div className="bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors cursor-pointer"><ArrowLeft className="w-5 h-5" /></button>
          <h1 className="text-lg font-semibold text-slate-800 dark:text-slate-200">个人设置</h1>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Avatar section */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4 flex items-center gap-2"><User className="w-4 h-4" />头像</h2>
          <div className="flex items-center gap-4">
            <div className="relative">
              {avatarUrl ? (
                <img src={avatarUrl} alt="avatar" className="w-16 h-16 rounded-full object-cover border-2 border-slate-200 dark:border-slate-600" />
              ) : (
                <div className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-white text-xl font-bold border-2 border-slate-200 dark:border-slate-600">
                  {(profile.username || profile.email || "?")[0].toUpperCase()}
                </div>
              )}
              <button onClick={() => fileInputRef.current?.click()} disabled={avatarUploading} className="absolute -bottom-1 -right-1 w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center text-white hover:bg-blue-600 transition-colors cursor-pointer disabled:opacity-50">
                <Camera className="w-3 h-3" />
              </button>
            </div>
            <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUploadAvatar(f); }} />
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">点击相机图标上传头像</p>
              <p className="text-xs text-slate-400">支持 JPG、PNG、GIF、WebP，最大 5MB</p>
              {avatarUploading && <p className="text-xs text-blue-500 mt-1">上传中...</p>}
            </div>
          </div>
        </div>

        {/* Username section */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">用户名</h2>
          <div className="flex gap-2">
            <input value={username} onChange={(e) => setUsername(e.target.value)} className="flex-1 px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 dark:focus:ring-blue-600" />
            <button onClick={handleSaveUsername} disabled={saving} className="px-4 py-2 rounded-xl bg-blue-500 text-white text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50 flex items-center gap-1 cursor-pointer">
              {saving ? <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" /> : <CheckCircle2 className="w-3 h-3" />}
              保存
            </button>
          </div>
          {usernameMsg && (
            <div className={`mt-2 text-xs flex items-center gap-1 ${usernameMsg.type === "success" ? "text-green-500" : "text-red-500"}`}>
              {usernameMsg.type === "success" ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
              {usernameMsg.text}
            </div>
          )}
        </div>

        {/* Password section */}
        <div className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4 flex items-center gap-2"><Lock className="w-4 h-4" />修改密码</h2>
          <div className="space-y-3">
            <input type="password" placeholder="当前密码" value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 dark:focus:ring-blue-600" />
            <input type="password" placeholder="新密码（至少 8 位）" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 dark:focus:ring-blue-600" />
            <input type="password" placeholder="确认新密码" value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)} className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 dark:focus:ring-blue-600" />
            <button onClick={handleChangePassword} disabled={pwdSaving} className="px-4 py-2 rounded-xl bg-blue-500 text-white text-sm font-medium hover:bg-blue-600 transition-colors disabled:opacity-50 flex items-center gap-1 cursor-pointer">
              {pwdSaving ? <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white" /> : null}
              修改密码
            </button>
          </div>
          {pwdMsg && (
            <div className={`mt-2 text-xs flex items-center gap-1 ${pwdMsg.type === "success" ? "text-green-500" : "text-red-500"}`}>
              {pwdMsg.type === "success" ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
              {pwdMsg.text}
            </div>
          )}
        </div>

        {/* Logout */}
        <button onClick={logout} className="w-full py-3 rounded-2xl border border-red-200 dark:border-red-800 text-red-500 dark:text-red-400 text-sm font-medium hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors flex items-center justify-center gap-2 cursor-pointer">
          <LogOut className="w-4 h-4" />退出登录
        </button>

        {/* Account info */}
        <div className="text-center text-xs text-slate-400">
          <p>账号: {profile.email}</p>
        </div>
      </div>
    </div>
  );
}
