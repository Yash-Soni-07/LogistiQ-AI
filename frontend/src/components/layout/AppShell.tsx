import { Outlet, useLocation, Navigate } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { useAuthStore } from '@/stores/auth.store';

export function AppShell() {
  const location = useLocation();
  const isAuthenticated = useAuthStore((s) => !!s.token);

  // Protected routes check
  if (!isAuthenticated && !location.pathname.startsWith('/login') && !location.pathname.startsWith('/register')) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Views that need full height/width without padding
  const pathname = location.pathname;
  const isFlush = ['/dashboard', '/tracking', '/routes', '/analytics', '/copilot', '/billing'].some(p => pathname === p || pathname.startsWith(p + '/'));

  return (
    <div className="lq-shell bg-[var(--lq-bg)]">
      <Sidebar />
      <div className="lq-main">
        <header className="lq-topbar border-b border-[var(--lq-border)] bg-[var(--lq-surface)] h-[52px] shrink-0">
          <TopBar />
        </header>
        <main className={`lq-content${isFlush ? ' lq-content--flush' : ''}`}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
