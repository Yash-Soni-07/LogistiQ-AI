import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  User, Shield, Bell, Palette, Cpu, LogOut, Save, CheckCircle2,
  Moon, Sun, Monitor, ChevronRight, Building2, Mail, KeyRound,
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useAuthStore } from '@/stores/auth.store';
import { useNavigate } from 'react-router-dom';

// ── Types ──

interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tenant_id: string;
  created_at: string;
  tenant: { id: string; name: string; created_at: string };
}

type ThemeMode = 'dark' | 'light' | 'system';

interface LocalPrefs {
  theme: ThemeMode;
  simulationAutostart: boolean;
  simulationSpeed: number;
  notifyDisruptions: boolean;
  notifySLA: boolean;
  notifyAgentLogs: boolean;
}

function getInitialTheme(): ThemeMode {
  try {
    const raw = localStorage.getItem('lq-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.theme === 'light' || parsed.theme === 'dark' || parsed.theme === 'system') return parsed.theme;
    }
  } catch { /* ignore */ }
  // Infer from current DOM state — don't override what's already set
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

const DEFAULT_PREFS: LocalPrefs = {
  theme: 'dark',
  simulationAutostart: true,
  simulationSpeed: 500,
  notifyDisruptions: true,
  notifySLA: true,
  notifyAgentLogs: false,
};

function loadPrefs(): LocalPrefs {
  try {
    const raw = localStorage.getItem('lq-settings');
    const base = raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS;
    // Always use the live theme, not the stored default
    base.theme = getInitialTheme();
    return base;
  } catch { return { ...DEFAULT_PREFS, theme: getInitialTheme() }; }
}

function savePrefs(prefs: LocalPrefs) {
  localStorage.setItem('lq-settings', JSON.stringify(prefs));
}

// ── Reusable Components ──

function Section({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-[var(--lq-border)] bg-[var(--lq-surface-2)]">
        <Icon size={15} className="text-[var(--lq-cyan)]" />
        <h2 className="text-xs font-semibold uppercase tracking-widest text-[var(--lq-text-bright)]">{title}</h2>
      </div>
      <div className="p-5 space-y-5">{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange, label, desc }: { checked: boolean; onChange: (v: boolean) => void; label: string; desc?: string }) {
  return (
    <label className="flex items-center justify-between cursor-pointer group">
      <div>
        <p className="text-sm font-medium text-[var(--lq-text-bright)] group-hover:text-[var(--lq-cyan)] transition-colors">{label}</p>
        {desc && <p className="text-xs text-[var(--lq-text-dim)] mt-0.5">{desc}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative w-10 h-[22px] rounded-full transition-colors duration-200 ${checked ? 'bg-[var(--lq-cyan)]' : 'bg-[var(--lq-border-hover)]'}`}
      >
        <span className={`absolute top-[3px] left-[3px] w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${checked ? 'translate-x-[18px]' : ''}`} />
      </button>
    </label>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--lq-border)] last:border-0">
      <span className="text-xs font-medium text-[var(--lq-text-dim)] uppercase tracking-wide">{label}</span>
      <span className="text-sm font-mono text-[var(--lq-text-bright)]">{value}</span>
    </div>
  );
}

// ── Main Page ──

export default function SettingsPage() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [prefs, setPrefs] = useState<LocalPrefs>(loadPrefs);
  const [saved, setSaved] = useState(false);

  const { data: profile } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => (await apiClient.get<UserProfile>('/auth/me')).data,
    staleTime: 60_000,
  });

  const update = (patch: Partial<LocalPrefs>) => {
    setPrefs(prev => {
      const next = { ...prev, ...patch };
      savePrefs(next);
      return next;
    });
  };

  // Apply theme
  useEffect(() => {
    const root = document.documentElement;
    if (prefs.theme === 'dark') root.classList.add('dark');
    else if (prefs.theme === 'light') root.classList.remove('dark');
    else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.classList.toggle('dark', prefersDark);
    }
  }, [prefs.theme]);

  // Sync simulation autostart env
  useEffect(() => {
    // Expose to VITE env read in DashboardView
    localStorage.setItem('lq-sim-autostart', prefs.simulationAutostart ? 'true' : 'false');
  }, [prefs.simulationAutostart]);

  const handleSave = () => {
    savePrefs(prefs);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const displayUser = profile ?? user;
  const themeOptions: { mode: ThemeMode; icon: React.ElementType; label: string }[] = [
    { mode: 'light', icon: Sun, label: 'Light' },
    { mode: 'dark', icon: Moon, label: 'Dark' },
    { mode: 'system', icon: Monitor, label: 'System' },
  ];

  return (
    <div className="flex flex-col h-full bg-[var(--lq-bg)] overflow-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-5 border-b border-[var(--lq-border)] bg-[var(--lq-surface)] shrink-0">
        <div>
          <h1 className="text-xl font-semibold text-[var(--lq-text-bright)]">Settings</h1>
          <p className="text-xs text-[var(--lq-text-dim)] mt-0.5">Manage your account, preferences and simulation controls.</p>
        </div>
        <button
          onClick={handleSave}
          className="flex items-center gap-2 px-4 py-2 bg-[var(--lq-cyan)] hover:opacity-90 text-white rounded-lg text-sm font-semibold transition-opacity shadow-sm"
        >
          {saved ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {saved ? 'Saved' : 'Save Changes'}
        </button>
      </div>

      <div className="flex-1 p-6 max-w-3xl w-full mx-auto space-y-6">

        {/* Profile */}
        <Section title="Account Profile" icon={User}>
          <InfoRow label="Full Name" value={displayUser?.full_name ?? '—'} />
          <InfoRow label="Email" value={displayUser?.email ?? '—'} />
          <InfoRow label="Role" value={displayUser?.role?.toUpperCase() ?? '—'} />
          {profile?.tenant && (
            <>
              <InfoRow label="Organization" value={profile.tenant.name} />
              <InfoRow label="Tenant ID" value={profile.tenant.id.slice(0, 12) + '…'} />
              <InfoRow label="Member Since" value={new Date(profile.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })} />
            </>
          )}
        </Section>

        {/* Appearance */}
        <Section title="Appearance" icon={Palette}>
          <div>
            <p className="text-sm font-medium text-[var(--lq-text-bright)] mb-3">Theme Mode</p>
            <div className="grid grid-cols-3 gap-3">
              {themeOptions.map(({ mode, icon: ThIcon, label }) => (
                <button
                  key={mode}
                  onClick={() => update({ theme: mode })}
                  className={`flex flex-col items-center gap-2 py-3 rounded-lg border transition-all text-sm font-medium ${
                    prefs.theme === mode
                      ? 'border-[var(--lq-cyan)] bg-[var(--lq-cyan-dim)] text-[var(--lq-cyan)]'
                      : 'border-[var(--lq-border)] bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] hover:border-[var(--lq-border-hover)]'
                  }`}
                >
                  <ThIcon size={18} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </Section>

        {/* Notifications */}
        <Section title="Notifications" icon={Bell}>
          <Toggle checked={prefs.notifyDisruptions} onChange={v => update({ notifyDisruptions: v })} label="Disruption Alerts" desc="Toast notifications for active supply chain disruptions." />
          <Toggle checked={prefs.notifySLA} onChange={v => update({ notifySLA: v })} label="SLA Breach Warnings" desc="Alerts when shipments approach SLA breach deadlines." />
          <Toggle checked={prefs.notifyAgentLogs} onChange={v => update({ notifyAgentLogs: v })} label="AI Agent Activity" desc="Stream real-time agent decision logs in dashboard." />
        </Section>

        {/* Simulation */}
        <Section title="Simulation Controls" icon={Cpu}>
          <Toggle checked={prefs.simulationAutostart} onChange={v => update({ simulationAutostart: v })} label="Auto-Start Simulation" desc="Automatically start logistics simulation when dashboard loads." />
          <div>
            <div className="flex items-center justify-between mb-2">
              <div>
                <p className="text-sm font-medium text-[var(--lq-text-bright)]">Speed Multiplier</p>
                <p className="text-xs text-[var(--lq-text-dim)]">Higher values = faster simulation ticks.</p>
              </div>
              <span className="text-sm font-mono font-bold text-[var(--lq-cyan)]">{prefs.simulationSpeed}×</span>
            </div>
            <input
              type="range"
              min={100}
              max={2000}
              step={100}
              value={prefs.simulationSpeed}
              onChange={e => update({ simulationSpeed: Number(e.target.value) })}
              className="w-full h-1.5 bg-[var(--lq-border)] rounded-full appearance-none cursor-pointer accent-[var(--lq-cyan)]"
            />
            <div className="flex justify-between text-[10px] text-[var(--lq-text-dim)] font-mono mt-1">
              <span>100×</span><span>1000×</span><span>2000×</span>
            </div>
          </div>
        </Section>

        {/* Security */}
        <Section title="Security & Access" icon={Shield}>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-[var(--lq-text-bright)]">Session Management</p>
              <p className="text-xs text-[var(--lq-text-dim)]">Your current session is active and secured via JWT.</p>
            </div>
            <div className="flex items-center gap-1.5 text-[var(--lq-green)] text-xs font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--lq-green)] animate-pulse" />
              Active
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 py-2.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 rounded-lg text-sm font-semibold transition-colors"
          >
            <LogOut size={15} />
            Sign Out
          </button>
        </Section>

      </div>
    </div>
  );
}
