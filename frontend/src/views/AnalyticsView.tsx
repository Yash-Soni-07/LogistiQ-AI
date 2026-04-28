import { useState } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from 'recharts';
import { CheckCircle2, AlertTriangle, TrendingUp, TrendingDown, DollarSign, Activity } from 'lucide-react';
import { cn } from '@/lib/utils';

// --- Mock Data ---

const SLA_DATA_7D = [
  { name: 'Mon', target: 95, actual: 96.2 },
  { name: 'Tue', target: 95, actual: 95.8 },
  { name: 'Wed', target: 95, actual: 94.1 },
  { name: 'Thu', target: 95, actual: 95.5 },
  { name: 'Fri', target: 95, actual: 97.0 },
  { name: 'Sat', target: 95, actual: 98.2 },
  { name: 'Sun', target: 95, actual: 97.5 },
];

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
  { name: 'Total Freight Spend', value: '$2.4M', trend: 'down', trendVal: '4.2%' },
  { name: 'Demurrage Avoided', value: '$184k', trend: 'up', trendVal: '12%' },
  { name: 'Expedited Costs', value: '$42k', trend: 'down', trendVal: '8.5%' },
  { name: 'AI Cost Savings', value: '$312k', trend: 'up', trendVal: '24%' },
];

const MODE_DISTRIBUTION = [
  { mode: 'Ocean Freight', percent: 45, color: 'var(--lq-cyan)' },
  { mode: 'Road Transport', percent: 35, color: 'var(--lq-amber)' },
  { mode: 'Air Freight', percent: 15, color: 'var(--lq-purple)' },
  { mode: 'Rail', percent: 5, color: 'var(--lq-green)' },
];

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

  return (
    <div className="flex flex-col h-full bg-[var(--lq-bg)] overflow-auto p-6">
      
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--lq-text-bright)] font-heading">Supply Chain Analytics</h1>
          <p className="text-[var(--lq-text-dim)] text-sm">AI-driven performance metrics and network health.</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-[var(--lq-surface)] border border-[var(--lq-border)] hover:bg-[var(--lq-surface-2)] text-[var(--lq-text-bright)] rounded-md text-sm transition-colors shadow-sm">
          <Activity size={16} />
          <span>Export Report</span>
        </button>
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
                <LineChart data={SLA_DATA_7D} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
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

            {/* Disruption Type Bar Chart */}
            <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">Disruptions by Type</h2>
              <div className="h-[220px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={DISRUPTION_DATA} layout="vertical" margin={{ top: 0, right: 20, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--lq-border)" horizontal={false} />
                    <XAxis type="number" stroke="var(--lq-text)" fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis dataKey="name" type="category" stroke="var(--lq-text-bright)" fontSize={11} tickLine={false} axisLine={false} width={100} />
                    <RechartsTooltip cursor={{ fill: 'var(--lq-surface-2)' }} content={<CustomTooltip />} />
                    <Bar dataKey="count" name="Incidents" radius={[0, 4, 4, 0]} barSize={20}>
                      {DISRUPTION_DATA.map((_entry, index) => (
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

          {/* Mode Distribution */}
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-4">Mode Distribution</h2>
            <div className="space-y-4">
              {MODE_DISTRIBUTION.map((mode, i) => (
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
    </div>
  );
}
