import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle, Clock, CornerUpRight, Search, Activity,
  CheckCircle2, ShieldAlert, Loader2, MapPin, Shield,
} from 'lucide-react';
import { apiClient } from '@/lib/api';

// ── Types (aligned with backend DisruptionRead schema) ──

interface Disruption {
  id: string;
  tenant_id: string;
  type: string;
  severity: string;
  status: string;
  radius_km: number | null;
  description: string | null;
  impact: string | null;
  created_at: string;
  updated_at: string;
}

interface AnalyticsSummary {
  total_shipments: number;
  delivered: number;
  in_transit: number;
  delayed: number;
  on_time_rate_pct: number;
  active_disruptions: number;
}

// ── Severity styling ──

const SEVERITY_STYLES: Record<string, { bg: string; border: string; text: string; icon: React.ElementType }> = {
  critical: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-[var(--lq-red)]', icon: AlertTriangle },
  high:     { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-[var(--lq-red)]', icon: AlertTriangle },
  medium:   { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-[var(--lq-amber)]', icon: ShieldAlert },
  low:      { bg: 'bg-blue-500/10', border: 'border-blue-500/30', text: 'text-[var(--lq-cyan)]', icon: Activity },
};

function getSeverityStyle(severity: string) {
  return SEVERITY_STYLES[severity.toLowerCase()] ?? SEVERITY_STYLES.low;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// ── Main Page ──

export default function RiskPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<'active' | 'resolved'>('active');

  // Fetch disruptions
  const { data: disruptionsData, isLoading } = useQuery({
    queryKey: ['disruptions', statusFilter],
    queryFn: async () => {
      const res = await apiClient.get<{ items: Disruption[]; total: number }>('/disruptions', {
        params: { status: statusFilter, limit: 50 },
      });
      return res.data;
    },
    refetchInterval: 15_000,
  });

  // Fetch KPIs
  const { data: summary } = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: async () => (await apiClient.get<AnalyticsSummary>('/analytics/summary')).data,
    staleTime: 30_000,
  });

  // Resolve mutation
  const resolveMutation = useMutation({
    mutationFn: async (disruptionId: string) => {
      await apiClient.patch(`/disruptions/${disruptionId}/resolve`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['disruptions'] });
      queryClient.invalidateQueries({ queryKey: ['analytics', 'summary'] });
    },
  });

  const disruptions = disruptionsData?.items ?? [];

  // Filter & sort
  const filtered = useMemo(() => {
    let items = disruptions;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      items = items.filter(d =>
        d.type.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        (d.description?.toLowerCase().includes(q)) ||
        (d.impact?.toLowerCase().includes(q))
      );
    }
    return items.sort((a, b) => {
      const sev = ['critical', 'high', 'medium', 'low'];
      const ai = sev.indexOf(a.severity.toLowerCase());
      const bi = sev.indexOf(b.severity.toLowerCase());
      if (ai !== bi) return ai - bi;
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [disruptions, searchQuery]);

  const selected = disruptions.find(d => d.id === selectedId);

  // Auto-select first
  if (!selectedId && filtered.length > 0 && !selected) {
    setTimeout(() => setSelectedId(filtered[0].id), 0);
  }

  // KPIs
  const delayedPct = summary ? (summary.delayed / Math.max(1, summary.total_shipments) * 100).toFixed(1) : '—';

  return (
    <div className="w-full h-full flex flex-col bg-[var(--lq-bg)] text-[var(--lq-text-bright)] overflow-hidden p-5 gap-5">

      {/* KPI Strip */}
      <div className="grid grid-cols-4 gap-4 shrink-0">
        {[
          { label: 'Active Disruptions', value: summary?.active_disruptions ?? '—', color: 'var(--lq-red)' },
          { label: 'Delayed Shipments', value: `${delayedPct}%`, color: 'var(--lq-amber)' },
          { label: 'On-Time Rate', value: summary ? `${summary.on_time_rate_pct}%` : '—', color: 'var(--lq-green)' },
          { label: 'Total In-Transit', value: summary?.in_transit ?? '—', color: 'var(--lq-cyan)' },
        ].map((kpi, i) => (
          <div key={i} className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-4 shadow-sm border-t-2" style={{ borderTopColor: kpi.color }}>
            <span className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold">{kpi.label}</span>
            <p className="text-2xl font-mono font-bold mt-1">{kpi.value}</p>
          </div>
        ))}
      </div>

      {/* Main Content */}
      <div className="flex flex-1 gap-5 min-h-0">

        {/* LEFT: Incident Feed */}
        <div className="w-[380px] shrink-0 flex flex-col gap-3 min-h-0 bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-4 shadow-sm">
          {/* Status Tabs */}
          <div className="flex gap-1 bg-[var(--lq-surface-2)] rounded-lg p-0.5 border border-[var(--lq-border)]">
            {(['active', 'resolved'] as const).map(s => (
              <button
                key={s}
                onClick={() => { setStatusFilter(s); setSelectedId(null); }}
                className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-colors capitalize ${
                  statusFilter === s ? 'bg-[var(--lq-surface)] text-[var(--lq-text-bright)] shadow-sm' : 'text-[var(--lq-text-dim)]'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--lq-text-dim)]" size={14} />
            <input
              type="text"
              placeholder="Search incidents…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg text-sm text-[var(--lq-text-bright)] outline-none focus:border-[var(--lq-cyan)] transition-colors"
            />
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={20} className="text-[var(--lq-text-dim)] animate-spin" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-12">
                <Shield size={28} className="mx-auto mb-2 text-[var(--lq-text-dim)] opacity-40" />
                <p className="text-xs text-[var(--lq-text-dim)]">
                  {statusFilter === 'active' ? 'No active incidents. All clear.' : 'No resolved incidents found.'}
                </p>
              </div>
            ) : (
              filtered.map(inc => {
                const styles = getSeverityStyle(inc.severity);
                const Icon = styles.icon;
                const isSelected = selectedId === inc.id;
                return (
                  <button
                    key={inc.id}
                    onClick={() => setSelectedId(inc.id)}
                    className={`w-full text-left p-3.5 rounded-lg border cursor-pointer transition-all duration-150 ${
                      isSelected
                        ? 'border-[var(--lq-cyan)] bg-[var(--lq-cyan-dim)]'
                        : 'border-[var(--lq-border)] hover:border-[var(--lq-border-hover)] bg-[var(--lq-surface-2)]'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <div className={`p-1 rounded ${styles.bg} border ${styles.border}`}>
                          <Icon size={13} className={styles.text} />
                        </div>
                        <div>
                          <p className="text-xs font-mono text-[var(--lq-text-dim)]">{inc.id.slice(0, 8)}…</p>
                          <p className="text-sm font-semibold">{formatType(inc.type)}</p>
                        </div>
                      </div>
                      {inc.status === 'active' ? (
                        <span className="w-2 h-2 rounded-full bg-[var(--lq-red)] animate-pulse mt-1.5" />
                      ) : (
                        <CheckCircle2 size={14} className="text-[var(--lq-green)] mt-1" />
                      )}
                    </div>
                    {inc.description && (
                      <p className="text-xs text-[var(--lq-text-dim)] line-clamp-1 mb-1.5">{inc.description}</p>
                    )}
                    <div className="flex items-center gap-3 text-[10px] text-[var(--lq-text-dim)]">
                      <span className="flex items-center gap-1"><Clock size={10} /> {timeAgo(inc.created_at)}</span>
                      <span className={`uppercase tracking-wider font-semibold ${styles.text}`}>{inc.severity}</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* RIGHT: Detail Pane */}
        <div className="flex-1 min-h-0 bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl flex flex-col overflow-hidden shadow-sm">
          {selected ? (
            <>
              {/* Header */}
              <div className="p-5 border-b border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex items-start justify-between">
                <div>
                  <h2 className="text-xl font-bold mb-1 flex items-center gap-2.5">
                    {formatType(selected.type)}
                    <span className={`text-[9px] uppercase tracking-widest px-2 py-0.5 rounded border font-semibold ${getSeverityStyle(selected.severity).bg} ${getSeverityStyle(selected.severity).text} ${getSeverityStyle(selected.severity).border}`}>
                      {selected.severity}
                    </span>
                  </h2>
                  <p className="text-xs text-[var(--lq-text-dim)] font-mono flex items-center gap-2">
                    {selected.id.slice(0, 12)}… · {selected.status.toUpperCase()}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold mb-1">Status</p>
                  {selected.status === 'active' ? (
                    <span className="text-[var(--lq-red)] font-mono font-bold text-sm flex items-center gap-1.5 justify-end">
                      <span className="w-2 h-2 rounded-full bg-[var(--lq-red)] animate-pulse" />
                      ACTIVE
                    </span>
                  ) : (
                    <span className="text-[var(--lq-green)] font-mono font-bold text-sm">RESOLVED</span>
                  )}
                </div>
              </div>

              {/* Content */}
              <div className="flex-1 flex overflow-hidden">
                {/* Left: Details */}
                <div className="w-1/2 border-r border-[var(--lq-border)] p-5 overflow-y-auto space-y-5">
                  <div>
                    <h3 className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold mb-3">Incident Details</h3>
                    <div className="space-y-3">
                      {[
                        { icon: Activity, label: 'Type', value: formatType(selected.type) },
                        { icon: ShieldAlert, label: 'Severity', value: selected.severity.toUpperCase() },
                        { icon: MapPin, label: 'Radius', value: selected.radius_km ? `${selected.radius_km} km` : 'N/A' },
                        { icon: Clock, label: 'Reported', value: new Date(selected.created_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) },
                      ].map(({ icon: RowIcon, label, value }, i) => (
                        <div key={i} className="flex items-center gap-3 py-2 border-b border-[var(--lq-border)] last:border-0">
                          <RowIcon size={13} className="text-[var(--lq-text-dim)] shrink-0" />
                          <span className="text-xs text-[var(--lq-text-dim)] w-20 shrink-0">{label}</span>
                          <span className="text-sm font-medium">{value}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {selected.description && (
                    <div>
                      <h3 className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold mb-2">Description</h3>
                      <p className="text-sm text-[var(--lq-text)] leading-relaxed bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg p-3">{selected.description}</p>
                    </div>
                  )}

                  {selected.impact && (
                    <div>
                      <h3 className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold mb-2">Impact Assessment</h3>
                      <p className="text-sm text-[var(--lq-text)] leading-relaxed bg-red-500/5 border border-red-500/15 rounded-lg p-3">{selected.impact}</p>
                    </div>
                  )}
                </div>

                {/* Right: Actions */}
                <div className="w-1/2 p-5 flex flex-col">
                  <h3 className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-widest font-semibold mb-4">Mitigation Workflows</h3>

                  <div className="space-y-3">
                    <button
                      onClick={() => selected && resolveMutation.mutate(selected.id)}
                      disabled={resolveMutation.isPending || selected.status === 'resolved'}
                      className="w-full flex items-center justify-between p-4 bg-[var(--lq-surface-2)] hover:bg-[var(--lq-border)] border border-[var(--lq-border)] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed group"
                    >
                      <div className="flex items-center gap-3">
                        <CheckCircle2 size={15} className="text-[var(--lq-green)]" />
                        <span className="font-semibold text-sm">Mark as Resolved</span>
                      </div>
                      {resolveMutation.isPending ? (
                        <Loader2 size={14} className="animate-spin text-[var(--lq-text-dim)]" />
                      ) : (
                        <span className="text-[10px] font-mono text-[var(--lq-text-dim)] group-hover:text-[var(--lq-green)]">EXECUTE</span>
                      )}
                    </button>

                    <button
                      disabled={selected.status === 'resolved'}
                      className="w-full flex items-center gap-3 p-4 bg-[var(--lq-surface-2)] hover:bg-[var(--lq-border)] border border-[var(--lq-border)] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <CornerUpRight size={15} className="text-[var(--lq-cyan)]" />
                      <span className="font-semibold text-sm">Auto-Reroute Fleet</span>
                    </button>

                    <button
                      disabled={selected.status === 'resolved'}
                      className="w-full flex items-center gap-3 p-4 bg-[var(--lq-surface-2)] hover:bg-[var(--lq-border)] border border-[var(--lq-border)] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Clock size={15} className="text-[var(--lq-amber)]" />
                      <span className="font-semibold text-sm">Hold at Origin Warehouse</span>
                    </button>

                    <button
                      disabled={selected.status === 'resolved'}
                      className="w-full flex items-center gap-3 p-4 bg-[var(--lq-surface-2)] hover:bg-[var(--lq-border)] border border-[var(--lq-border)] rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <AlertTriangle size={15} className="text-[var(--lq-red)]" />
                      <span className="font-semibold text-sm">Escalate to Hub Manager</span>
                    </button>
                  </div>

                  {/* Status feedback */}
                  {selected.status === 'resolved' && (
                    <div className="mt-auto p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-[var(--lq-green)] flex items-start gap-3">
                      <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-bold mb-0.5">Incident Resolved</p>
                        <p className="text-xs opacity-80">This disruption has been marked as resolved. No further action required.</p>
                      </div>
                    </div>
                  )}

                  {resolveMutation.isSuccess && selected.status === 'active' && (
                    <div className="mt-auto p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-[var(--lq-green)] flex items-start gap-3">
                      <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-bold mb-0.5">Resolution Dispatched</p>
                        <p className="text-xs opacity-80">Incident marked resolved. Data refreshing…</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-[var(--lq-text-dim)] gap-3">
              <Activity size={32} className="opacity-20" />
              <p className="text-sm">Select an incident to view resolution workflows.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
