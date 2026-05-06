import { useEffect, useState, useRef, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { Bell, Sun, Moon, ChevronDown, User, CreditCard, LogOut, Flame, Siren, Loader2, SlidersHorizontal, Check, RotateCcw, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { useThemeStore } from '@/stores/theme.store';
import { useSimulationStore, type VisibleMode } from '@/stores/simulation.store';
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
  const { isDark, setDark } = useThemeStore();

  const toggle = () => {
    const next = !isDark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
    localStorage.setItem('lq-theme', next ? 'dark' : 'light');
  };

  return (
    <button className="lq-icon-btn" onClick={toggle} aria-label="Toggle theme">
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [liveUnread, setLiveUnread] = useState(0); // bumped on WS events
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

  // Silent background poll every 15s to keep unread count fresh
  useEffect(() => {
    const poll = async () => {
      try {
        const { apiClient } = await import('@/lib/api');
        const res = await apiClient.get('/disruptions?limit=10');
        const items: any[] = Array.isArray(res.data) ? res.data : res.data?.items || [];
        const unread = items.filter((n: any) => !readIds.has(n.id)).length;
        setLiveUnread(unread);
      } catch { /* silent */ }
    };
    poll();
    const id = setInterval(poll, 15_000);
    return () => clearInterval(id);
  }, [readIds]);

  // Fetch disruptions when opened (full list)
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
          setLiveUnread(0); // reset badge after opening
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
  const totalUnread = open ? unreadCount : Math.max(unreadCount, liveUnread);

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
    window.location.href = '/login';
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
            onClick={() => { window.location.href = '/settings'; setOpen(false); }}
          >
            <User size={14} /> Profile
          </button>
          <button
            className="lq-dropdown-item"
            role="menuitem"
            onClick={() => { window.location.href = '/billing'; setOpen(false); }}
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

// ── Mode meta for the settings panel ────────────────────────────────────────
const MODE_META: { id: VisibleMode; label: string; color: string }[] = [
  { id: 'road', label: 'Road',       color: 'rgb(139,92,246)'  },
  { id: 'air',  label: 'Air',        color: 'rgb(236,72,153)'  },
  { id: 'sea',  label: 'Sea',        color: 'rgb(14,165,233)'  },
  { id: 'rail', label: 'Rail',       color: 'rgb(16,185,129)'  },
];

function SimSettingsPanel() {
  const { visibleModes, setVisibleModes, speedMultiplier, setSpeedMultiplier } = useSimulationStore();
  const [open, setOpen]            = useState(false);
  const [draft, setDraft]          = useState<VisibleMode[]>([]);
  const [draftSpeed, setDraftSpeed] = useState(100);
  const [reSimOpen, setReSimOpen]  = useState(false);
  const [reSimModes, setReSimModes] = useState<VisibleMode[]>(['road','air','sea']);
  const [saved, setSaved]          = useState(false);
  const [saving, setSaving]        = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) {
      setDraft([...visibleModes]);
      setDraftSpeed(speedMultiplier);
      setSaved(false);
      setReSimOpen(false);
    }
  }, [open, visibleModes, speedMultiplier]);

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const toggle = (id: VisibleMode) =>
    setDraft(prev => prev.includes(id) ? prev.filter(m => m !== id) : [...prev, id]);

  const toggleReSim = (id: VisibleMode) =>
    setReSimModes(prev => prev.includes(id) ? prev.filter(m => m !== id) : [...prev, id]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const { apiClient } = await import('@/lib/api');
      // Update visible modes locally
      setVisibleModes(draft);
      // Update speed on server without restart
      if (draftSpeed !== speedMultiplier) {
        await apiClient.patch(`/simulation/speed?speed_multiplier=${draftSpeed}`);
        setSpeedMultiplier(draftSpeed);
      }
      setSaved(true);
      setTimeout(() => { setOpen(false); setSaved(false); }, 700);
    } catch {
      setSaved(false);
    } finally {
      setSaving(false);
    }
  }, [draft, draftSpeed, speedMultiplier, setVisibleModes, setSpeedMultiplier]);

  const handleReSimulate = useCallback(async () => {
    if (reSimModes.length === 0) return;
    try {
      const { apiClient } = await import('@/lib/api');
      const { toast } = await import('sonner');
      await apiClient.post(`/simulation/demo?restart=true&modes=${reSimModes.join(',')}`);
      setVisibleModes(reSimModes);
      setReSimOpen(false);
      setOpen(false);
      toast.success(`Re-simulating ${reSimModes.join(', ')} transports…`);
    } catch (e: unknown) {
      const { toast } = await import('sonner');
      toast.error(`Re-simulate failed: ${e instanceof Error ? e.message : 'Network error'}`);
    }
  }, [reSimModes, setVisibleModes]);

  const allSelected = MODE_META.every(m => draft.includes(m.id));
  const toggleAll   = () => setDraft(allSelected ? [] : MODE_META.map(m => m.id));

  const speedLabel = (v: number) => v >= 1000 ? `${(v/1000).toFixed(1)}k×` : `${v}×`;

  return (
    <div className="relative" ref={panelRef}>
      <button
        id="sim-settings-btn"
        onClick={() => setOpen(o => !o)}
        title="Map Simulation Settings"
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-[11px] font-bold tracking-wide transition-all select-none',
          open
            ? 'bg-[var(--lq-cyan)]/20 text-[var(--lq-cyan)] shadow-[0_0_0_1px_rgba(34,211,238,0.4)]'
            : 'bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] hover:text-[var(--lq-cyan)] hover:bg-[var(--lq-cyan)]/10 border border-[var(--lq-border)]'
        )}
      >
        <SlidersHorizontal size={12} />
        <span>Map Settings</span>
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 w-[280px] bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl shadow-[0_16px_40px_rgba(0,0,0,0.35)] z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex items-center gap-2">
            <SlidersHorizontal size={12} className="text-[var(--lq-cyan)]" />
            <span className="text-[10px] font-bold text-[var(--lq-text-bright)] uppercase tracking-widest">Map Settings</span>
          </div>

          <div className="p-3 space-y-4">
            {/* Transport Modes */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] font-semibold text-[var(--lq-text-dim)] uppercase tracking-wider">Visible Modes</p>
                <button onClick={toggleAll} className="text-[9px] font-semibold text-[var(--lq-cyan)] hover:underline">
                  {allSelected ? 'Deselect All' : 'Select All'}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {MODE_META.map(m => {
                  const active = draft.includes(m.id);
                  return (
                    <button key={m.id} onClick={() => toggle(m.id)}
                      className={cn(
                        'flex items-center gap-2 px-2.5 py-2 rounded-lg border transition-all text-left',
                        active ? 'bg-[var(--lq-surface-2)] border-[var(--lq-border-hover)]' : 'bg-transparent border-transparent opacity-45 hover:opacity-70'
                      )}
                    >
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: m.color }} />
                      <span className="flex-1 text-xs font-medium text-[var(--lq-text-bright)]">{m.label}</span>
                      <span className={cn('w-3.5 h-3.5 rounded border flex items-center justify-center shrink-0', active ? 'bg-[var(--lq-cyan)] border-[var(--lq-cyan)]' : 'border-[var(--lq-border)]')}>
                        {active && <Check size={9} className="text-[var(--lq-bg)]" strokeWidth={3} />}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Simulation Speed */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-[10px] font-semibold text-[var(--lq-text-dim)] uppercase tracking-wider">Simulation Speed</p>
                <span className="text-[11px] font-mono font-bold text-[var(--lq-cyan)]">{speedLabel(draftSpeed)}</span>
              </div>
              <input
                type="range" min={10} max={2000} step={10}
                value={draftSpeed}
                onChange={e => setDraftSpeed(Number(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-[var(--lq-cyan)] bg-[var(--lq-surface-2)]"
              />
              <div className="flex justify-between text-[9px] text-[var(--lq-text-dim)] mt-1">
                <span>Slow (10×)</span><span>Fast (2000×)</span>
              </div>
            </div>

            {/* Re-Simulate */}
            <div>
              <button
                onClick={() => setReSimOpen(o => !o)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--lq-surface-2)] border border-[var(--lq-border)] hover:border-[var(--lq-cyan)]/40 transition-colors text-xs font-semibold text-[var(--lq-text-bright)]"
              >
                <RotateCcw size={12} className="text-[var(--lq-cyan)]" />
                Re-Simulate Transports
                <ChevronDown size={10} className={cn('ml-auto transition-transform', reSimOpen && 'rotate-180')} />
              </button>
              {reSimOpen && (
                <div className="mt-2 p-2 bg-[var(--lq-surface-2)] rounded-lg border border-[var(--lq-border)] space-y-1">
                  <p className="text-[9px] text-[var(--lq-text-dim)] mb-2">Select modes to re-simulate (restarts simulation):</p>
                  {MODE_META.filter(m => ['road','air','sea'].includes(m.id)).map(m => {
                    const active = reSimModes.includes(m.id);
                    return (
                      <button key={m.id} onClick={() => toggleReSim(m.id)}
                        className={cn('w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors', active ? 'text-[var(--lq-text-bright)]' : 'opacity-50 text-[var(--lq-text-dim)]')}
                      >
                        <span className="w-2 h-2 rounded-full" style={{ background: m.color }} />
                        {m.label}
                        <span className={cn('ml-auto w-3.5 h-3.5 rounded border flex items-center justify-center', active ? 'bg-[var(--lq-cyan)] border-[var(--lq-cyan)]' : 'border-[var(--lq-border)]')}>
                          {active && <Check size={8} className="text-[var(--lq-bg)]" strokeWidth={3} />}
                        </span>
                      </button>
                    );
                  })}
                  <button onClick={handleReSimulate}
                    className="w-full mt-2 py-1.5 rounded text-xs font-bold bg-[var(--lq-purple)]/20 text-[var(--lq-purple)] border border-[var(--lq-purple)]/30 hover:bg-[var(--lq-purple)]/30 transition-colors flex items-center justify-center gap-1.5"
                  >
                    <Zap size={11} /> Re-Simulate Selected
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Save */}
          <div className="px-3 pb-3">
            <button
              onClick={handleSave}
              disabled={saving}
              className={cn(
                'w-full py-2 rounded-lg text-xs font-bold transition-all',
                saved ? 'bg-[var(--lq-green)]/20 text-[var(--lq-green)] border border-[var(--lq-green)]/30'
                : saving ? 'bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] border border-[var(--lq-border)] cursor-wait'
                : 'bg-[var(--lq-cyan)] text-[var(--lq-bg)] hover:opacity-90 active:scale-[.98]'
              )}
            >
              {saved ? '✓ Saved' : saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Custom fire toast with animated countdown bar ─────────────────────────────────
// Duration must match toast duration (12000ms)
const FIRE_TOAST_MS = 12000;

function FireToast({ toastId, origin, destination }: { toastId: string | number; origin: string; destination: string }) {
  const [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());
  const pausedAtRef = useRef(0);

  useEffect(() => {
    let rafId: number;
    const tick = () => {
      if (!paused) setElapsed(Date.now() - startRef.current);
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [paused]);

  const onMouseEnter = () => { setPaused(true); pausedAtRef.current = Date.now(); };
  const onMouseLeave = () => {
    // Shift start time forward by how long we were paused
    startRef.current += Date.now() - pausedAtRef.current;
    setPaused(false);
  };

  const pct = Math.min(100, (elapsed / FIRE_TOAST_MS) * 100);

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className="relative w-[360px] bg-[var(--lq-surface)] border border-red-500/30 rounded-xl shadow-2xl overflow-hidden"
    >
      <div className="p-3.5">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-lg bg-red-500/15 flex items-center justify-center shrink-0">
            <Flame size={16} className="text-orange-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-bold text-red-400">🔥 Fire Disruption Active</p>
            <p className="text-xs text-[var(--lq-text-bright)] mt-0.5">
              Road shipment <strong>{origin} → {destination}</strong> affected.
            </p>
            <p className="text-xs text-[var(--lq-text-dim)] mt-0.5">VRP alternates computed. Trucks and AI agents notified.</p>
            <a
              href="/routes"
              className="inline-flex items-center gap-1 mt-2 text-[11px] font-semibold text-[var(--lq-cyan)] hover:underline"
            >
              Open Route Optimizer →
            </a>
          </div>
          <button
            onClick={() => toast.dismiss(toastId)}
            className="text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)] transition-colors shrink-0"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      </div>
      {/* Timer bar */}
      <div className="h-0.5 bg-[var(--lq-border)]">
        <div
          className="h-full bg-red-500 transition-none origin-left"
          style={{ width: `${100 - pct}%` }}
        />
      </div>
    </div>
  );
}

function SimulateDropdown() {
  const { visibleModes } = useSimulationStore();
  const [open, setOpen] = useState(false);
  const [firing, setFiring] = useState(false);
  const [lastResult, setLastResult] = useState<{ origin: string; destination: string } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

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
      const res = await apiClient.post('/simulation/disruption/fire');
      if (res.data.status === 'error') {
        toast.error(res.data.message ?? 'Could not trigger disruption. Is the simulation running?');
      } else {
        const origin = res.data.shipment_origin;
        const destination = res.data.shipment_destination;
        setLastResult({ origin, destination });
        // Custom toast with countdown timer bar — stays on screen for 12s, pauses on hover
        toast.custom((id) => <FireToast toastId={id} origin={origin} destination={destination} />, {
          duration: 12000,
          id: 'fire-disruption',
        });
      }
    } catch (err: unknown) {
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
              Disruptions inject a critical fire event on an active <strong className="text-[var(--lq-text-bright)]">Road</strong> shipment. This triggers the VRP engine and Gemini Decision Agents.<br/>
              {!visibleModes.includes('road') && (
                <span className="text-amber-400 font-bold mt-1 block">⚠️ Road mode is currently disabled in Map Settings.</span>
              )}
            </p>
            {lastResult && (
              <p className="text-[9px] text-red-400 mt-1">
                Last Event: 🔥 {lastResult.origin} → {lastResult.destination}
              </p>
            )}
          </div>

          {/* Action items */}
          <div className="p-2">
            <button
              id="simulate-fire-btn"
              onClick={handleFire}
              disabled={firing || !visibleModes.includes('road')}
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
                <p className="text-[10px] text-[var(--lq-text-dim)] mt-0.5">
                  {!visibleModes.includes('road') ? 'Enable road transport first.' : 'Blocks route & computes alternates.'}
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
        <SimSettingsPanel />
        <SimulateDropdown />
        <ISTClock />
        <ThemeToggle />
        <NotificationBell />
        <UserMenu />
      </div>
    </div>
  );
}
