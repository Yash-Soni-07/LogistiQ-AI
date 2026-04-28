import os

files = {
    'src/lib/api.ts': """import axios, { type AxiosError } from 'axios';
import { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth.store';

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
});

// Request — inject auth headers
apiClient.interceptors.request.use((config) => {
  const { token, tenant } = useAuthStore.getState();
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  if (tenant?.id) {
    config.headers['X-Tenant-ID'] = tenant.id;
  }
  return config;
});

// Response — handle 401 globally
apiClient.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      useAuthStore.getState().logout();
      // Hard redirect — avoids circular React Router dependency
      window.location.replace('/login');
    }
    return Promise.reject(err);
  },
);

// ---------------------------------------------------------------------------
// TanStack Query client
// ---------------------------------------------------------------------------

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});
""",

    'src/components/layout/AppShell.tsx': """import { Outlet, useLocation, Navigate } from 'react-router-dom';
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
  const isFlush = ['/dashboard', '/tracking', '/routes', '/analytics', '/copilot'].some(p => pathname === p || pathname.startsWith(p + '/'));

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
""",

    'src/components/layout/TopBar.tsx': """import { useEffect, useState, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Bell, Sun, Moon, ChevronDown, User, CreditCard, LogOut } from 'lucide-react';
import { useAuthStore } from '@/stores/auth.store';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AgentStatus = 'active' | 'idle' | 'error';

interface Agent {
  id: string;
  label: string;
  color: string; // CSS color for the dot
  status: AgentStatus;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENTS: Agent[] = [
  { id: 'sentinel', label: 'Sentinel', color: '#22d3ee', status: 'active' },
  { id: 'router', label: 'Router', color: '#a78bfa', status: 'active' },
  { id: 'decision', label: 'Decision', color: '#fbbf24', status: 'idle' },
  { id: 'copilot', label: 'Copilot', color: '#34d399', status: 'active' },
];

const ROUTE_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  tracking: 'Shipments',
  risk: 'Risk & Alerts',
  routes: 'Route Optimizer',
  analytics: 'Analytics',
  reports: 'Reports',
  copilot: 'AI Copilot',
  billing: 'Billing',
  settings: 'Settings',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function AgentPill({ agent }: { agent: Agent }) {
  return (
    <div className="lq-agent-pill" data-status={agent.status}>
      <span
        className={cn(
          'lq-agent-dot',
          agent.status === 'active' && 'lq-agent-dot--pulse',
        )}
        style={{ '--dot-color': agent.color } as React.CSSProperties}
      />
      <span className="lq-agent-label">{agent.label}</span>
    </div>
  );
}

function ISTClock() {
  const [time, setTime] = useState('');

  useEffect(() => {
    const fmt = new Intl.DateTimeFormat('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    const tick = () => setTime(fmt.format(new Date()));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="lq-clock" aria-label="Current IST time">
      <span className="lq-clock-label">IST</span>
      <span className="lq-clock-time">{time}</span>
    </div>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(
    () => document.documentElement.classList.contains('dark'),
  );

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
    localStorage.setItem('lq-theme', next ? 'dark' : 'light');
  };

  return (
    <button className="lq-icon-btn" onClick={toggle} aria-label="Toggle theme">
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function NotificationBell({ count = 3 }: { count?: number }) {
  return (
    <button className="lq-icon-btn lq-bell-btn" aria-label={`${count} notifications`}>
      <Bell size={16} />
      {count > 0 && (
        <span className="lq-badge" aria-hidden="true">
          {count > 9 ? '9+' : count}
        </span>
      )}
    </button>
  );
}

function UserMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const initials = user?.fullName
    ? user.fullName
        .split(' ')
        .map((n) => n[0])
        .join('')
        .slice(0, 2)
        .toUpperCase()
    : 'U';

  return (
    <div className="lq-user-menu" ref={menuRef}>
      <button
        className="lq-avatar-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="User menu"
      >
        <span className="lq-avatar">{initials}</span>
        <ChevronDown size={12} className={cn('lq-chevron', open && 'lq-chevron--open')} />
      </button>

      {open && (
        <div className="lq-dropdown" role="menu">
          <div className="lq-dropdown-header">
            <p className="lq-dropdown-name">{user?.fullName ?? 'User'}</p>
            <p className="lq-dropdown-email">{user?.email ?? ''}</p>
          </div>
          <hr className="lq-dropdown-divider" />
          <button
            className="lq-dropdown-item"
            role="menuitem"
            onClick={() => { navigate('/settings'); setOpen(false); }}
          >
            <User size={14} /> Profile
          </button>
          <button
            className="lq-dropdown-item"
            role="menuitem"
            onClick={() => { navigate('/billing'); setOpen(false); }}
          >
            <CreditCard size={14} /> Billing
          </button>
          <hr className="lq-dropdown-divider" />
          <button
            className="lq-dropdown-item lq-dropdown-item--danger"
            role="menuitem"
            onClick={handleLogout}
          >
            <LogOut size={14} /> Sign Out
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TopBar
// ---------------------------------------------------------------------------

export function TopBar() {
  const { pathname } = useLocation();
  const segment = pathname.split('/').filter(Boolean)[0] ?? 'dashboard';
  const pageLabel = ROUTE_LABELS[segment] ?? segment;

  return (
    <div className="lq-topbar-inner">
      {/* Left: Breadcrumb */}
      <nav className="lq-breadcrumb" aria-label="Breadcrumb">
        <span className="lq-breadcrumb-root">LogistiQ</span>
        <span className="lq-breadcrumb-sep" aria-hidden="true">/</span>
        <span className="lq-breadcrumb-current">{pageLabel}</span>
      </nav>

      {/* Center: Agent status pills */}
      <div className="lq-agents" role="status" aria-label="Agent status">
        {AGENTS.map((agent) => (
          <AgentPill key={agent.id} agent={agent} />
        ))}
      </div>

      {/* Right: Controls */}
      <div className="lq-topbar-controls">
        <ISTClock />
        <ThemeToggle />
        <NotificationBell count={3} />
        <UserMenu />
      </div>
    </div>
  );
}
""",

    'src/stores/auth.store.ts': """import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  fullName: string;
  tenant_id: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  tenant: { id: string } | null;
  login: (token: string, user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      tenant: null,
      login: (token, user) => set({ token, user, tenant: { id: user.tenant_id } }),
      logout: () => set({ token: null, user: null, tenant: null }),
    }),
    { name: 'auth-storage' }
  )
);
""",

    'src/stores/sidebar.store.ts': """import { create } from 'zustand';

interface SidebarState {
  expanded: boolean;
  toggle: () => void;
  setExpanded: (expanded: boolean) => void;
}

export const useSidebarStore = create<SidebarState>((set) => ({
  expanded: true,
  toggle: () => set((state) => ({ expanded: !state.expanded })),
  setExpanded: (expanded) => set({ expanded }),
}));
""",

    'src/stores/alert.store.ts': """import { create } from 'zustand';

interface AlertState {
  disruptions: any[];
  setDisruptions: (disruptions: any[]) => void;
}

export const useAlertStore = create<AlertState>((set) => ({
  disruptions: [],
  setDisruptions: (disruptions) => set({ disruptions }),
}));
""",

    'src/stores/shipment.store.ts': """import { create } from 'zustand';

interface ShipmentState {
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
}

export const useShipmentStore = create<ShipmentState>((set) => ({
  selectedId: null,
  setSelectedId: (selectedId) => set({ selectedId }),
}));
""",

    'src/stores/map.store.ts': """import { create } from 'zustand';

interface MapState {
  viewport: { longitude: number; latitude: number; zoom: number; pitch: number; bearing: number };
  setViewport: (vp: any) => void;
}

export const useMapStore = create<MapState>((set) => ({
  viewport: { longitude: 0, latitude: 0, zoom: 2, pitch: 0, bearing: 0 },
  setViewport: (viewport) => set({ viewport }),
}));
""",

    'src/hooks/useWebSocket.ts': """import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/auth.store';

export function useWebSocket(path: string, onMessage: (data: any) => void) {
  const [isConnected, setIsConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    const token = useAuthStore.getState().token;
    if (!token) return;

    const url = new URL(path, import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws');
    url.searchParams.set('token', token);

    const socket = new WebSocket(url.toString());
    
    socket.onopen = () => setIsConnected(true);
    socket.onclose = () => setIsConnected(false);
    socket.onmessage = (e) => {
      try {
        onMessage(JSON.parse(e.data));
      } catch (err) {
        onMessage(e.data);
      }
    };

    ws.current = socket;

    return () => {
      socket.close();
    };
  }, [path, onMessage]);

  return { isConnected, ws: ws.current };
}
""",

    'src/components/layout/Sidebar.tsx': """import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Package, AlertTriangle, Route, BarChart2, FileText, Bot, Settings, ChevronLeft, ChevronRight } from 'lucide-react';
import { useSidebarStore } from '@/stores/sidebar.store';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard size={20} /> },
  { path: '/tracking', label: 'Shipments', icon: <Package size={20} /> },
  { path: '/risk', label: 'Risk & Alerts', icon: <AlertTriangle size={20} /> },
  { path: '/routes', label: 'Route Optimizer', icon: <Route size={20} /> },
  { path: '/analytics', label: 'Analytics', icon: <BarChart2 size={20} /> },
  { path: '/reports', label: 'Reports', icon: <FileText size={20} /> },
  { path: '/copilot', label: 'AI Copilot', icon: <Bot size={20} /> },
  { path: '/settings', label: 'Settings', icon: <Settings size={20} /> },
];

export function Sidebar() {
  const { expanded, toggle } = useSidebarStore();

  return (
    <aside className={cn("lq-sidebar bg-[var(--lq-surface)] border-r border-[var(--lq-border)] flex flex-col transition-all duration-300", expanded ? "w-[var(--sidebar-w)]" : "w-16")}>
      <div className="lq-sidebar-header h-[52px] flex items-center justify-between px-4 border-b border-[var(--lq-border)] shrink-0">
        {expanded ? (
          <div className="flex items-center gap-2 text-[var(--lq-text-bright)] font-bold text-lg">
            <div className="w-6 h-6 rounded bg-[var(--lq-cyan)] flex items-center justify-center text-white text-xs">L</div>
            <span>LogistiQ</span>
          </div>
        ) : (
          <div className="w-8 h-8 rounded bg-[var(--lq-cyan)] flex items-center justify-center text-white font-bold mx-auto">L</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-4 flex flex-col gap-1 px-2 lq-nav-scroll">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2 rounded-md transition-colors",
                isActive 
                  ? "bg-[var(--lq-cyan-dim)] text-[var(--lq-cyan)] font-medium" 
                  : "text-[var(--lq-text-dim)] hover:bg-[var(--lq-surface-2)] hover:text-[var(--lq-text)]"
              )
            }
          >
            <span className="shrink-0">{item.icon}</span>
            {expanded && <span className="whitespace-nowrap">{item.label}</span>}
          </NavLink>
        ))}
      </div>

      <div className="p-4 border-t border-[var(--lq-border)] flex justify-center shrink-0">
        <button onClick={toggle} className="p-1.5 rounded bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)] transition-colors">
          {expanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>
    </aside>
  );
}
"""
}

# Create missing wrappers dynamically
pages = ['Dashboard', 'Tracking', 'Analytics', 'Copilot', 'Routes', 'Risk', 'Reports', 'Settings', 'Billing', 'Login', 'Register']
for p in pages:
    view_name = f"{p}View" if p not in ['Login', 'Register', 'Settings', 'Billing', 'Reports', 'Risk'] else None
    if view_name:
        content = f"import {view_name} from '@/views/{view_name}';\n\nexport default function {p}Page() {{\n  return <{view_name} />;\n}}\n"
    else:
        content = f"export default function {p}Page() {{\n  return <div className=\"p-8 text-[var(--lq-text-bright)]\">{p} Page - Under Construction</div>;\n}}\n"
    files[f"src/pages/{p}Page.tsx"] = content

# Write to files
for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("Restoration script completed successfully!")
