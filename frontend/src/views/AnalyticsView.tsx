import { useState, useMemo, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from 'recharts';
import { CheckCircle2, AlertTriangle, TrendingUp, TrendingDown, DollarSign, Activity, Package, Download, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api';

// --- Mock Data ---

// --- Types ---
interface KpiSummary { total_shipments: number; in_transit: number; on_time_rate_pct: number; active_disruptions: number; delayed: number; }
interface ModeCount { mode: string; count: number; }
interface DisruptionRow { day: string; type: string; count: number; }

// --- SLA data per period ---
const SLA_DATA: Record<string, { name: string; target: number; actual: number }[]> = {
  '7D': [
    { name: 'Mon', target: 95, actual: 96.2 },
    { name: 'Tue', target: 95, actual: 95.8 },
    { name: 'Wed', target: 95, actual: 94.1 },
    { name: 'Thu', target: 95, actual: 95.5 },
    { name: 'Fri', target: 95, actual: 97.0 },
    { name: 'Sat', target: 95, actual: 98.2 },
    { name: 'Sun', target: 95, actual: 97.5 },
  ],
  '30D': [
    { name: 'Apr W1', target: 95, actual: 92.4 },
    { name: 'Apr W2', target: 95, actual: 93.8 },
    { name: 'Apr W3', target: 95, actual: 94.5 },
    { name: 'Apr W4', target: 95, actual: 95.2 },
    { name: 'May W1', target: 95, actual: 97.1 },
  ],
  '90D': [
    { name: 'Feb',    target: 95, actual: 91.2 },
    { name: 'Mar W1', target: 95, actual: 92.8 },
    { name: 'Mar W3', target: 95, actual: 93.4 },
    { name: 'Apr W1', target: 95, actual: 94.0 },
    { name: 'Apr W3', target: 95, actual: 95.1 },
    { name: 'May W1', target: 95, actual: 97.5 },
  ],
};


const DISRUPTION_DATA = [
  { name: 'Weather', count: 42 },
  { name: 'Port Congestion', count: 28 },
  { name: 'Customs Delay', count: 18 },
  { name: 'Carrier Capacity', count: 12 },
  { name: 'Strike Action', count: 5 },
];

const AI_BENCHMARKS = [
  { name: 'Route Optimization Rate', value: '94.2%', targetMet: true },
  { name: 'Avg. Decision Latency', value: '1.2s', targetMet: true },
  { name: 'Automated Reroutes', value: '128', targetMet: true },
  { name: 'False Positive Alerts', value: '12.5%', targetMet: false }, // amber
  { name: 'Carrier Auction Win Rate', value: '68%', targetMet: false }, // amber
  { name: 'CO₂ Reduction vs Base', value: '-14.2%', targetMet: true },
];

const COST_IMPACT = [
  { name: 'Total Freight Spend', value: '₹2.04Cr', trend: 'down', trendVal: '4.2%' },
  { name: 'Demurrage Avoided', value: '₹18.4L', trend: 'up', trendVal: '12%' },
  { name: 'Expedited Costs', value: '₹3.6L', trend: 'down', trendVal: '8.5%' },
  { name: 'AI Cost Savings', value: '₹31.2L', trend: 'up', trendVal: '24%' },
];

const MODE_FALLBACK = [
  { mode: 'Ocean Freight', percent: 45, color: 'var(--lq-cyan)' },
  { mode: 'Road Transport', percent: 35, color: 'var(--lq-amber)' },
  { mode: 'Air Freight', percent: 15, color: 'var(--lq-purple)' },
  { mode: 'Rail', percent: 5, color: 'var(--lq-green)' },
];


const MODE_COLOR: Record<string, string> = { road: 'var(--lq-amber)', air: 'var(--lq-purple)', sea: 'var(--lq-cyan)', rail: 'var(--lq-green)' };
const MODE_LABEL: Record<string, string> = { road: 'Road Transport', air: 'Air Freight', sea: 'Ocean Freight', rail: 'Rail' };

// Skeleton loader
const Skele = ({ w = 'w-full', h = 'h-4' }: { w?: string; h?: string }) => (
  <div className={cn('animate-pulse rounded bg-[var(--lq-surface-2)]', w, h)} />
);

// --- Custom Recharts Tooltip ---
const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] p-3 rounded-lg shadow-xl">
        <p className="text-[var(--lq-text-bright)] font-semibold mb-2">{label}</p>
        {payload.map((entry: any, index: number) => (
          <div key={index} className="flex items-center gap-2 text-sm mb-1">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-[var(--lq-text-dim)]">{entry.name}:</span>
            <span className="font-mono text-[var(--lq-text-bright)]">{entry.value}</span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

// --- Components ---

export default function AnalyticsView() {
  const [period, setPeriod] = useState<'7D' | '30D' | '90D'>('7D');

  // --- Live API hooks ---
  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: async () => (await apiClient.get<KpiSummary>('/analytics/summary')).data,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });

  const { data: modeRaw } = useQuery({
    queryKey: ['analytics', 'by-mode'],
    queryFn: async () => (await apiClient.get<ModeCount[]>('/analytics/shipments/by-mode')).data,
    refetchInterval: 30_000,
  });

  const { data: disruptionRaw } = useQuery({
    queryKey: ['analytics', 'disruptions-trend'],
    queryFn: async () => (await apiClient.get<DisruptionRow[]>('/analytics/disruptions/trend?days=30')).data,
    refetchInterval: 60_000,
  });

  // Derived: mode distribution (real API → fallback mock)
  const modeDistribution = useMemo(() => {
    if (!modeRaw || modeRaw.length === 0) return MODE_FALLBACK;
    const total = modeRaw.reduce((s, d) => s + d.count, 0);
    if (total === 0) return MODE_FALLBACK;
    return modeRaw
      .filter(d => d.count > 0)
      .map(d => ({
        mode: MODE_LABEL[d.mode] ?? d.mode,
        percent: Math.round((d.count / total) * 100),
        color: MODE_COLOR[d.mode] ?? 'var(--lq-border-hover)',
      }))
      .sort((a, b) => b.percent - a.percent);
  }, [modeRaw]);

  // Derived: disruption bar data (real → fallback)
  const disruptionData = useMemo(() => {
    if (disruptionRaw && disruptionRaw.length > 0) {
      const byType = disruptionRaw.reduce<Record<string, number>>((acc, r) => {
        acc[r.type] = (acc[r.type] ?? 0) + r.count;
        return acc;
      }, {});
      const labels: Record<string, string> = { fire: 'Fire / Hazard', flood: 'Flood', storm: 'Storm', strike: 'Strike Action', port_congestion: 'Port Congestion', customs: 'Customs Delay', carrier: 'Carrier Capacity' };
      const rows = Object.entries(byType).map(([t, c]) => ({ name: labels[t] ?? t, count: c })).sort((a, b) => b.count - a.count);
      if (rows.length > 0) return rows;
    }
    return DISRUPTION_DATA;
  }, [disruptionRaw]);

  // KPI values: real when available, sensible mock otherwise
  const totalShipments = (!sumLoading && summary?.total_shipments) ? summary.total_shipments : 248;
  const inTransit     = (!sumLoading && summary?.in_transit != null && summary.in_transit > 0) ? summary.in_transit : 9;
  const slaRate       = (!sumLoading && summary?.on_time_rate_pct != null && summary.on_time_rate_pct > 0) ? summary.on_time_rate_pct.toFixed(1) : '94.2';
  const activeDisr    = (!sumLoading && summary?.active_disruptions != null) ? summary.active_disruptions : 0;

  // Print-to-PDF export — generates a styled HTML report in a new tab
  const handleExport = useCallback(() => {
    const now = new Date();
    const dateStr = now.toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
    const timeStr = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

    const kpiRows = [
      ['Total Shipments', String(totalShipments), `${inTransit} in-transit`],
      ['SLA Adherence', `${slaRate}%`, 'On-time delivery rate'],
      ['Active Disruptions', String(activeDisr), activeDisr > 0 ? 'Needs attention' : 'Network clear'],
      ['AI Cost Savings', '₹31.2L', '+24% this quarter'],
    ];

    const modeRows = modeDistribution.map(m => `
      <tr><td>${m.mode}</td><td>${m.percent}%</td>
      <td><div style="background:#e2e8f0;border-radius:4px;height:8px;width:100%"><div style="background:#0ea5e9;height:8px;border-radius:4px;width:${m.percent}%"></div></div></td></tr>`).join('');

    const benchRows = AI_BENCHMARKS.map(b => `
      <tr><td>${b.name}</td><td style="font-weight:600;color:${b.targetMet ? '#10b981' : '#f59e0b'}">${b.value}</td>
      <td style="color:${b.targetMet ? '#10b981' : '#f59e0b'}">${b.targetMet ? '✓ On target' : '⚠ Review'}</td></tr>`).join('');

    const costRows = COST_IMPACT.map(c => `
      <tr><td>${c.name}</td><td style="font-weight:700">${c.value}</td>
      <td style="color:${c.trend === 'up' ? '#10b981' : '#0ea5e9'}">${c.trend === 'up' ? '↑' : '↓'} ${c.trendVal}</td></tr>`).join('');

    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>LogistiQ AI — Analytics Report ${dateStr}</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',Arial,sans-serif;color:#0f172a;background:#fff;padding:40px;font-size:13px}
  .header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:32px;padding-bottom:20px;border-bottom:2px solid #0ea5e9}
  .brand{font-size:22px;font-weight:800;color:#0ea5e9;letter-spacing:-0.5px}
  .brand span{color:#0f172a}
  .meta{text-align:right;color:#64748b;font-size:12px;line-height:1.6}
  h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#0ea5e9;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid #e2e8f0}
  table{width:100%;border-collapse:collapse;margin-bottom:8px}
  th{background:#f1f5f9;text-align:left;padding:8px 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b}
  td{padding:8px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
  tr:last-child td{border-bottom:none}
  .kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:8px}
  .kpi-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;border-top:3px solid #0ea5e9}
  .kpi-label{font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;margin-bottom:6px}
  .kpi-value{font-size:22px;font-weight:800;color:#0f172a;margin-bottom:2px}
  .kpi-sub{font-size:11px;color:#94a3b8}
  .footer{margin-top:40px;padding-top:16px;border-top:1px solid #e2e8f0;display:flex;justify-content:space-between;color:#94a3b8;font-size:11px}
  .badge-green{color:#10b981;font-weight:600} .badge-amber{color:#f59e0b;font-weight:600}
  @media print{body{padding:24px}.no-print{display:none}}
</style></head><body>

<div class="header">
  <div><div class="brand">LogistiQ <span>AI</span></div>
    <div style="color:#64748b;font-size:12px;margin-top:4px">Supply Chain Intelligence Platform</div>
  </div>
  <div class="meta">
    <div style="font-weight:600;font-size:14px">Analytics Report</div>
    <div>${dateStr} · ${timeStr}</div>
    <div>Generated by LogistiQ AI</div>
  </div>
</div>

<h2>Executive KPIs</h2>
<div class="kpi-grid">
  ${kpiRows.map(([label, val, sub]) => `
    <div class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${val}</div>
      <div class="kpi-sub">${sub}</div>
    </div>`).join('')}
</div>

<h2>Cost Impact</h2>
<table><thead><tr><th>Metric</th><th>Value</th><th>Trend</th></tr></thead><tbody>${costRows}</tbody></table>

<h2>Mode Distribution</h2>
<table><thead><tr><th>Transport Mode</th><th>Share</th><th>Visual</th></tr></thead><tbody>${modeRows}</tbody></table>

<h2>AI Agent Benchmarks</h2>
<table><thead><tr><th>Benchmark</th><th>Result</th><th>Status</th></tr></thead><tbody>${benchRows}</tbody></table>

<h2>Disruption Summary (Last 30 Days)</h2>
<table><thead><tr><th>Type</th><th>Incidents</th></tr></thead><tbody>
  ${DISRUPTION_DATA.map(d => `<tr><td>${d.name}</td><td style="font-weight:600">${d.count}</td></tr>`).join('')}
</tbody></table>

<h2>Carbon Impact</h2>
<table><thead><tr><th>Initiative</th><th>CO₂ Saved</th></tr></thead><tbody>
  <tr><td>Ocean Route Optimization (slow-steaming AI)</td><td class="badge-green">−8.4 kt</td></tr>
  <tr><td>Intermodal Shift (Road → Rail)</td><td class="badge-green">−5.8 kt</td></tr>
  <tr><td>Total Quarterly Reduction</td><td class="badge-green" style="font-size:15px">−14.2 kt CO₂</td></tr>
</tbody></table>

<div class="footer">
  <span>LogistiQ AI · Confidential · For internal use only</span>
  <span>© ${now.getFullYear()} LogistiQ AI Platform</span>
</div>

<script>window.onload = () => window.print();</script>
</body></html>`;

    const win = window.open('', '_blank');
    if (win) { win.document.write(html); win.document.close(); }
  }, [totalShipments, inTransit, slaRate, activeDisr, modeDistribution]);

  const slaData = SLA_DATA[period];

  return (
    <div className="flex flex-col h-full bg-[var(--lq-bg)] overflow-auto">

      {/* Sticky Header */}
      <div className="sticky top-0 z-10 bg-[var(--lq-surface)] border-b border-[var(--lq-border)] px-6 py-4 flex items-center justify-between shadow-sm">
        <div>
          <h1 className="text-xl font-semibold text-[var(--lq-text-bright)] font-heading flex items-center gap-2">
            <Activity size={18} className="text-[var(--lq-cyan)]" />
            Supply Chain Analytics
          </h1>
          <p className="text-[var(--lq-text-dim)] text-xs mt-0.5">AI-driven performance metrics and network health.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[var(--lq-green)] bg-[var(--lq-green)]/10 border border-[var(--lq-green)]/20 px-2.5 py-1 rounded-full font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--lq-green)] animate-pulse" />
            Live
          </div>
          <button onClick={handleExport} className="flex items-center gap-2 px-4 py-2 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] hover:bg-[var(--lq-surface)] text-[var(--lq-text-bright)] rounded-md text-sm transition-colors shadow-sm">
            <Download size={14} />
            Export Report
          </button>
        </div>
      </div>

      <div className="p-6 space-y-6">

      {/* Live KPI Strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Shipments',     val: sumLoading ? null : totalShipments, sub: `${inTransit} in-transit`, icon: <Package size={15}/>, color: 'var(--lq-cyan)' },
          { label: 'SLA Adherence',       val: sumLoading ? null : `${slaRate}%`,  sub: '+2.1% vs last week',    icon: <CheckCircle2 size={15}/>, color: 'var(--lq-green)' },
          { label: 'Active Disruptions',  val: sumLoading ? null : activeDisr,     sub: activeDisr > 0 ? 'Needs attention' : 'Network clear', icon: <AlertTriangle size={15}/>, color: activeDisr > 0 ? 'var(--lq-amber)' : 'var(--lq-green)' },
          { label: 'AI Cost Savings',     val: '₹31.2L',                          sub: '+24% this quarter',     icon: <Zap size={15}/>, color: 'var(--lq-purple)' },
        ].map((k, i) => (
          <div key={i} className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-4 shadow-sm" style={{ borderTopWidth: 3, borderTopColor: k.color }}>
            <div className="flex items-center justify-between mb-2 text-[var(--lq-text-dim)]">
              <span className="text-[10px] font-semibold uppercase tracking-wider">{k.label}</span>
              <span style={{ color: k.color }}>{k.icon}</span>
            </div>
            <div className="text-2xl font-bold font-mono text-[var(--lq-text-bright)] leading-none mb-1">
              {k.val === null ? <Skele w="w-16" h="h-7" /> : k.val}
            </div>
            <div className="text-[10px] text-[var(--lq-text-dim)]">{k.sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-6">
        
        {/* =========================================================================
            LEFT COLUMN (2/3)
            ========================================================================= */}
        <div className="space-y-6">
          
          {/* SLA Trend Line Chart */}
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider">SLA Adherence Trend</h2>
              <div className="flex bg-[var(--lq-surface-2)] rounded-md p-1 border border-[var(--lq-border)]">
                {['7D', '30D', '90D'].map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p as any)}
                    className={cn(
                      "px-3 py-1 text-xs font-medium rounded transition-colors",
                      period === p 
                        ? "bg-[var(--lq-surface)] text-[var(--lq-text-bright)] shadow-sm" 
                        : "text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)]"
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
            
            <div className="h-[280px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={slaData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--lq-border)" vertical={false} />
                  <XAxis dataKey="name" stroke="var(--lq-text)" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="var(--lq-text)" fontSize={12} tickLine={false} axisLine={false} domain={[90, 100]} />
                  <RechartsTooltip content={<CustomTooltip />} />
                  <Line 
                    type="monotone" 
                    dataKey="target" 
                    name="Target SLA"
                    stroke="var(--lq-text-dim)" 
                    strokeWidth={2}
                    strokeDasharray="5 5" 
                    dot={false}
                  />
                  <Line 
                    type="monotone" 
                    dataKey="actual" 
                    name="Actual SLA"
                    stroke="var(--lq-cyan)" 
                    strokeWidth={3}
                    dot={{ fill: 'var(--lq-surface)', stroke: 'var(--lq-cyan)', strokeWidth: 2, r: 4 }}
                    activeDot={{ r: 6, fill: 'var(--lq-cyan)' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* AI Benchmark Grid */}
            <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">AI Agent Benchmarks</h2>
              <div className="grid grid-cols-2 gap-3">
                {AI_BENCHMARKS.map((bm, i) => (
                  <div key={i} className="bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded-lg p-3">
                    <div className="flex items-start justify-between mb-2">
                      <span className="text-[10px] text-[var(--lq-text)] uppercase tracking-wide leading-tight block">{bm.name}</span>
                      {bm.targetMet ? (
                        <CheckCircle2 size={14} className="text-[var(--lq-green)] shrink-0" />
                      ) : (
                        <AlertTriangle size={14} className="text-[var(--lq-amber)] shrink-0" />
                      )}
                    </div>
                    <span className="font-mono text-lg font-bold text-[var(--lq-text-bright)]">{bm.value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Disruption Type Bar Chart — real API data with mock fallback */}
            <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">Disruptions by Type <span className="text-[10px] font-normal text-[var(--lq-text-dim)] normal-case ml-1">Last 30 days</span></h2>
              <div className="h-[220px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={disruptionData} layout="vertical" margin={{ top: 0, right: 20, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--lq-border)" horizontal={false} />
                    <XAxis type="number" stroke="var(--lq-text)" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis dataKey="name" type="category" stroke="var(--lq-text-bright)" fontSize={11} tickLine={false} axisLine={false} width={110} />
                    <RechartsTooltip cursor={{ fill: 'var(--lq-surface-2)' }} content={<CustomTooltip />} />
                    <Bar dataKey="count" name="Incidents" radius={[0, 4, 4, 0]} barSize={20}>
                      {disruptionData.map((_entry, index) => (
                        <Cell key={`cell-${index}`} fill={index === 0 ? 'var(--lq-red)' : index === 1 ? 'var(--lq-amber)' : 'var(--lq-border-hover)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

        </div>

        {/* =========================================================================
            RIGHT COLUMN (1/3) - STACKED CARDS
            ========================================================================= */}
        <div className="space-y-6">
          
          {/* Cost Impact Grid */}
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4 flex items-center gap-2">
              <DollarSign size={16} className="text-[var(--lq-green)]" />
              Cost Impact
            </h2>
            <div className="grid grid-cols-2 gap-4">
              {COST_IMPACT.map((item, i) => {
                const isGood = item.trend === 'down' ? item.name !== 'AI Cost Savings' : item.name === 'AI Cost Savings';
                return (
                  <div key={i} className="space-y-1">
                    <span className="text-[11px] text-[var(--lq-text-dim)] uppercase tracking-wide">{item.name}</span>
                    <div className="flex items-end gap-2">
                      <span className="font-mono text-xl font-bold text-[var(--lq-text-bright)] leading-none">{item.value}</span>
                      <div className={cn(
                        "flex items-center text-[10px] font-medium px-1 py-0.5 rounded",
                        isGood ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-red-500/10 text-red-700 dark:text-red-400'
                      )}>
                        {item.trend === 'up' ? <TrendingUp size={10} className="mr-0.5" /> : <TrendingDown size={10} className="mr-0.5" />}
                        {item.trendVal}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Mode Distribution — real API data with mock fallback */}
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">Mode Distribution</h2>
            <div className="space-y-4">
              {modeDistribution.map((mode, i) => (
                <div key={i}>
                  <div className="flex items-center justify-between text-xs mb-1.5">
                    <span className="text-[var(--lq-text-bright)] font-medium">{mode.mode}</span>
                    <span className="font-mono text-[var(--lq-text-dim)]">{mode.percent}%</span>
                  </div>
                  <div className="h-2 w-full bg-[var(--lq-surface-2)] rounded-full overflow-hidden border border-[var(--lq-border)]">
                    <div className="h-full rounded-full transition-all duration-1000" style={{ width: `${mode.percent}%`, backgroundColor: mode.color }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Carbon Tracker */}
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">Carbon Tracker</h2>
            <div className="flex flex-col items-center justify-center py-6 bg-[var(--lq-bg)] rounded-lg border border-[var(--lq-border)]">
              <span className="text-4xl font-mono font-bold text-[var(--lq-green)] mb-1">-14.2<span className="text-lg text-[var(--lq-text-dim)] ml-1">kt</span></span>
              <span className="text-xs text-[var(--lq-text-dim)] uppercase tracking-wider">CO₂ Saved This Quarter</span>
            </div>
            
            <div className="mt-5 relative">
              <div className="absolute left-[9px] top-2 bottom-2 w-px bg-[var(--lq-border)]" />
              <div className="space-y-4 relative">
                <div className="flex gap-3">
                  <div className="w-[19px] h-[19px] shrink-0 rounded-full bg-[var(--lq-bg)] border-2 border-[var(--lq-green)] z-10 mt-0.5" />
                  <div>
                    <p className="text-sm text-[var(--lq-text-bright)] font-medium">Ocean Route Optimization</p>
                    <p className="text-xs text-[var(--lq-text-dim)]">Saved 8.4kt via slow-steaming AI</p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <div className="w-[19px] h-[19px] shrink-0 rounded-full bg-[var(--lq-bg)] border-2 border-[var(--lq-cyan)] z-10 mt-0.5" />
                  <div>
                    <p className="text-sm text-[var(--lq-text-bright)] font-medium">Intermodal Shift</p>
                    <p className="text-xs text-[var(--lq-text-dim)]">Saved 5.8kt shifting Road to Rail</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

      </div>

      </div>{/* end p-6 space-y-6 */}
    </div>
  );
}
