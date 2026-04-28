import { useEffect, useState, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Bell, Sun, Moon, ChevronDown, User, CreditCard, LogOut, Flame, Siren, Loader2 } from 'lucide-react';
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

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [readIds, setReadIds] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem('lq-read-notifs');
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch { return new Set(); }
  });
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Fetch disruptions when opened
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const { apiClient } = await import('@/lib/api');
        const res = await apiClient.get('/disruptions?limit=10');
        if (!cancelled) {
          const items = Array.isArray(res.data) ? res.data : res.data?.items || [];
          setNotifications(items.slice(0, 10));
        }
      } catch {
        // silent
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  const unreadCount = notifications.filter(n => !readIds.has(n.id)).length;
  const totalUnread = open ? unreadCount : Math.max(unreadCount, 0);

  const markAllRead = () => {
    const ids = new Set(notifications.map((n: any) => n.id));
    setReadIds(ids);
    localStorage.setItem('lq-read-notifs', JSON.stringify([...ids]));
  };

  const severityColor = (sev: string) => {
    if (sev === 'critical' || sev === 'high') return 'text-red-400';
    if (sev === 'medium') return 'text-amber-400';
    return 'text-blue-400';
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        className="lq-icon-btn lq-bell-btn"
        aria-label={`${totalUnread} notifications`}
        onClick={() => setOpen(o => !o)}
      >
        <Bell size={16} />
        {totalUnread > 0 && (
          <span className="lq-badge" aria-hidden="true">
            {totalUnread > 9 ? '9+' : totalUnread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 w-[360px] bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl shadow-2xl z-50 overflow-hidden"
          style={{ maxHeight: '460px' }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--lq-border)] bg-[var(--lq-surface-2)]">
            <h4 className="text-xs font-bold text-[var(--lq-text-bright)] uppercase tracking-wider">Notifications</h4>
            {notifications.length > 0 && (
              <button onClick={markAllRead} className="text-[10px] text-[var(--lq-cyan)] hover:underline font-semibold">
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="overflow-y-auto" style={{ maxHeight: '380px', scrollbarWidth: 'thin', scrollbarColor: 'var(--lq-border) transparent' }}>
            {loading ? (
              <div className="flex items-center justify-center py-10">
                <div className="lq-spinner" />
              </div>
            ) : notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 opacity-50">
                <Bell size={24} className="mb-2 text-[var(--lq-text-dim)]" />
                <p className="text-xs text-[var(--lq-text-dim)]">No recent notifications</p>
              </div>
            ) : (
              notifications.map((n: any) => {
                const isRead = readIds.has(n.id);
                return (
                  <div
                    key={n.id}
                    className={cn(
                      'px-4 py-3 border-b border-[var(--lq-border)] hover:bg-[var(--lq-surface-2)] transition-colors cursor-pointer',
                      !isRead && 'bg-[var(--lq-cyan)]/5 border-l-2 border-l-[var(--lq-cyan)]'
                    )}
                    onClick={() => {
                      setReadIds(prev => {
                        const next = new Set(prev);
                        next.add(n.id);
                        localStorage.setItem('lq-read-notifs', JSON.stringify([...next]));
                        return next;
                      });
                    }}
                  >
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <p className="text-xs font-medium text-[var(--lq-text-bright)] leading-relaxed line-clamp-2">
                        {n.description || n.event_type || 'Disruption Alert'}
                      </p>
                      {n.severity && (
                        <span className={cn('text-[9px] uppercase font-bold shrink-0', severityColor(n.severity))}>
                          {n.severity}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[9px] text-[var(--lq-text-dim)]">
                      {n.event_type && <span className="capitalize">{n.event_type.replace('_', ' ')}</span>}
                      {n.created_at && (
                        <span>{new Date(n.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span>
                      )}
                      {n.status && (
                        <span className={cn(
                          'px-1.5 py-0.5 rounded text-[8px] uppercase font-bold',
                          n.status === 'active' ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'
                        )}>
                          {n.status}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
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

  const initials = user?.full_name
    ? user.full_name
        .split(' ')
        .map((n: string) => n[0])
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
            <p className="lq-dropdown-name">{user?.full_name ?? 'User'}</p>
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

function SimulateDropdown() {
  const [open, setOpen] = useState(false);
  const [firing, setFiring] = useState(false);
  const [lastResult, setLastResult] = useState<{ origin: string; destination: string } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleFire = async () => {
    setFiring(true);
    try {
      const { apiClient } = await import('@/lib/api');
      const { toast } = await import('sonner');
      const res = await apiClient.post('/simulation/disruption/fire');
      if (res.data.status === 'error') {
        toast.error(res.data.message ?? 'Could not trigger disruption. Is the simulation running?');
      } else {
        setLastResult({ origin: res.data.shipment_origin, destination: res.data.shipment_destination });
        toast.warning(
          `🔥 Fire on road shipment ${res.data.shipment_origin} → ${res.data.shipment_destination}. ${res.data.alternate_routes_count ?? 0} VRP routes computed.`,
          { duration: 6000 },
        );
        navigate('/routes');
      }
    } catch (err: unknown) {
      const { toast } = await import('sonner');
      const msg = err instanceof Error ? err.message : 'Network error';
      toast.error(`Disruption trigger failed: ${msg}`);
    } finally {
      setFiring(false);
      setOpen(false);
    }
  };

  return (
    <div className="relative" ref={menuRef}>
      {/* Trigger button — red pill */}
      <button
        id="simulate-disruption-btn"
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-bold tracking-wide transition-all select-none',
          open
            ? 'bg-red-500/20 text-red-400 shadow-[0_0_0_1px_rgba(239,68,68,0.4)]'
            : 'bg-red-500/10 text-red-400/80 hover:bg-red-500/20 hover:text-red-400 hover:shadow-[0_0_0_1px_rgba(239,68,68,0.3)]'
        )}
      >
        <Siren size={12} className={cn('transition-transform', open && 'animate-pulse')} />
        SIMULATE
        <ChevronDown size={10} className={cn('transition-transform duration-200', open && 'rotate-180')} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full right-0 mt-2 w-[300px] bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl shadow-[0_16px_40px_rgba(0,0,0,0.4)] z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-[var(--lq-border)] flex items-center gap-2">
            <Siren size={13} className="text-red-400" />
            <span className="text-[10px] font-bold text-[var(--lq-text-bright)] uppercase tracking-widest">Disruption Scenarios</span>
          </div>

          {/* Context info */}
          <div className="px-4 py-2 bg-[var(--lq-surface-2)] border-b border-[var(--lq-border)]">
            <p className="text-[9px] text-[var(--lq-text-dim)] leading-relaxed">
              Simulation runs <strong className="text-[var(--lq-text-bright)]">3 live shipments</strong> — 1 Road · 1 Air · 1 Sea.<br />
              Disruptions affect the <strong className="text-[var(--lq-text-bright)]">road</strong> shipment and trigger the Sentinel + Decision agents.
            </p>
            {lastResult && (
              <p className="text-[9px] text-amber-400 mt-1">
                Last: 🔥 {lastResult.origin} → {lastResult.destination}
              </p>
            )}
          </div>

          {/* Action items */}
          <div className="p-2">
            <button
              id="simulate-fire-btn"
              onClick={handleFire}
              disabled={firing}
              className="w-full flex items-start gap-3 px-3 py-3 rounded-lg hover:bg-red-500/8 border border-transparent hover:border-red-500/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-red-500/20 to-orange-500/10 border border-red-500/20 flex items-center justify-center shrink-0 mt-0.5">
                {firing
                  ? <Loader2 size={16} className="text-red-400 animate-spin" />
                  : <Flame size={16} className="text-orange-400" />}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[var(--lq-text-bright)] group-hover:text-red-300 transition-colors">
                  {firing ? 'Triggering disruption…' : 'Simulate Fire Disruption'}
                </p>
                <p className="text-[9px] text-[var(--lq-text-dim)] mt-0.5 leading-relaxed">
                  Triggers fire on NH road segment → Sentinel detects →
                  Decision Agent reroutes via OSRM VRP → Gemini confirms
                </p>
              </div>
            </button>
          </div>

          {/* Footer */}
          <div className="px-4 py-2 border-t border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[9px] text-[var(--lq-text-dim)]">All 3 transport modes active · Gemini Decision Agent online</span>
          </div>
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
        <SimulateDropdown />
        <ISTClock />
        <ThemeToggle />
        <NotificationBell />
        <UserMenu />
      </div>
    </div>
  );
}
