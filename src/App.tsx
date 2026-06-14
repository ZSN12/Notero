import { Suspense, lazy } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { isAuthenticated } from "@/services/auth";
import ErrorBoundary from "@/components/ErrorBoundary";

// Lazy-load pages to reduce initial bundle size
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const ChapterList = lazy(() => import("@/pages/ChapterList"));
const NoteDetail = lazy(() => import("@/pages/NoteDetail"));
const Login = lazy(() => import("@/pages/Login"));
const SharePage = lazy(() => import("@/pages/SharePage"));
const Profile = lazy(() => import("@/pages/Profile"));

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

function PageSpinner() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-slate-50 dark:bg-slate-900">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-blue-600 dark:border-slate-600 dark:border-t-blue-400" />
    </div>
  );
}

export default function App() {
  return (
    <Router>
      <Toaster position="top-right" richColors closeButton />
      <Suspense fallback={<PageSpinner />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/share/:sessionId" element={<SharePage />} />
          <Route path="/" element={<ProtectedRoute><ErrorBoundary><Dashboard /></ErrorBoundary></ProtectedRoute>} />
          <Route path="/subject/:id" element={<ProtectedRoute><ErrorBoundary><ChapterList /></ErrorBoundary></ProtectedRoute>} />
          <Route path="/subject/:id/session/:sessionId" element={<ProtectedRoute><ErrorBoundary><NoteDetail /></ErrorBoundary></ProtectedRoute>} />
          <Route path="/profile" element={<ProtectedRoute><ErrorBoundary><Profile /></ErrorBoundary></ProtectedRoute>} />
        </Routes>
      </Suspense>
    </Router>
  );
}
