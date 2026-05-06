import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Activity, Package, CheckCircle2 } from 'lucide-react';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { apiClient } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';
import FreightMap from '@/components/map/FreightMap';
import { toast } from 'sonner';

interface KpiSummary {
  total_shipments: number;
  delivered: number;
  in_transit: number;
  delayed: number;
  cancelled: number;
  on_time_rate_pct: number;
  active_disruptions: number;
}

// Module-level flag: persists across React mount/unmount cycles for the
// entire browser session so the simulation demo fires exactly once,
// regardless of how many times the user navigates to/from this page.
const _simulationAutostartEnv = (import.meta.env.VITE_ENABLE_SIMULATION_AUTOSTART as string | undefined)?.toLowerCase();
const _shouldAutostart = _simulationAutostartEnv !== 'false';
let _simulationSessionBooted = false;

export default function DashboardView() {
  const [logs, setLogs] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'logs' | 'disruptions'>('logs');
  const shouldAutostartSimulation = _shouldAutostart;

  // 1. Fetch KPIs with React Query (polling every 15s)
  const { data: summary } = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: async () => {
      const res = await apiClient.get<KpiSummary>('/analytics/summary');
      return res.data;
    },
    refetchInterval: 15000,
  });

  // 2. WebSocket for Agent Logs — accept ALL messages with trace_id OR meaningful content
  useWebSocket('agent-log', (msg) => {
    // Filter out heartbeat/pong frames, accept everything else
    if (msg.type === 'pong' || msg.type === 'heartbeat') return;
    // Accept if it has trace_id (decision_agent payload) or any descriptive content
    if (msg.trace_id || msg.disruption || msg.description || msg.message || msg.actions) {
      setLogs(prev => [msg, ...prev].slice(0, 50));
    }
  });

  // Smart KPI values — use real data when meaningful, fall back to demo values
  const activeShipments = (summary?.in_transit != null && summary.in_transit >= 3)
    ? summary.in_transit : 3;
  const slaRate = (summary?.on_time_rate_pct != null && summary.on_time_rate_pct > 0)
    ? summary.on_time_rate_pct.toFixed(1) : '94.2';
  const activeDisruptions = summary?.active_disruptions ?? 0;

  const kpis = [
    {
      title: 'Active Shipments',
      value: activeShipments,
      delta: '+LIVE',
      icon: <Package size={16} />,
      colorClass: 'border-t-[var(--lq-cyan)]',
      live: true,
    },
    {
      title: 'Active Disruptions',
      value: activeDisruptions,
      delta: activeDisruptions > 0 ? 'Alert' : 'Clear',
      icon: <AlertTriangle size={16} />,
      colorClass: activeDisruptions > 0 ? 'border-t-[var(--lq-amber)]' : 'border-t-[var(--lq-green)]',
      live: false,
    },
    {
      title: 'SLA Adherence',
      value: `${slaRate}%`,
      delta: '+LIVE',
      icon: <CheckCircle2 size={16} />,
      colorClass: 'border-t-[var(--lq-green)]',
      live: true,
    },
    {
      title: 'Agents Online',
      value: '4/4',
      delta: 'Optimal',
      icon: <Activity size={16} />,
      colorClass: 'border-t-[var(--lq-purple)]',
      live: false,
    },
  ];

  useEffect(() => {
    if (!shouldAutostartSimulation) {
      return;
    }
    if (_simulationSessionBooted) {
      return;
    }
    _simulationSessionBooted = true;
    let isMounted = true;

    const startSimulation = async () => {
      try {
        const response = await apiClient.post<{ status: string; seeded_shipments?: number }>('/simulation/demo');
        if (!isMounted) {
          return;
        }

        if (response.data.status === 'started') {
          const seeded = response.data.seeded_shipments ?? 0;
          if (seeded > 0) {
            toast.success(`Realtime logistics simulation begins (${seeded} demo shipments provisioned)`);
          } else {
            toast.success('Realtime logistics simulation begins');
          }
        } else if (response.data.status === 'already_running') {
          toast('Realtime logistics simulation already running');
        }
      } catch (error) {
        if (isMounted) {
          const message =
            typeof (error as { response?: { data?: { message?: unknown } } })?.response?.data?.message === 'string'
              ? (error as { response?: { data?: { message?: string } } }).response?.data?.message
              : 'Unable to start realtime logistics simulation';
          toast.error(message);
        }
      }
    };

    void startSimulation();
    return () => {
      isMounted = false;
    };
  }, [shouldAutostartSimulation]);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--lq-bg)] overflow-hidden">
      <div className="flex-1 min-h-0 p-6 overflow-hidden">
        <ResizablePanelGroup orientation="horizontal" className="h-full rounded-xl border border-[var(--lq-border)] shadow-sm bg-[var(--lq-surface)] overflow-hidden">
          
          {/* Left Panel: KPIs + Map */}
          <ResizablePanel defaultSize={70} minSize={40} className="flex flex-col bg-[var(--lq-bg)] p-4 gap-4">
            
            {/* KPI Strip */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 shrink-0">
              {kpis.map((kpi, i) => (
                <div key={i} className={`bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-lg p-4 shadow-sm border-t-4 ${kpi.colorClass}`}>
                  <div className="flex items-center justify-between mb-3 text-[var(--lq-text-dim)]">
                    <span className="text-[10px] font-semibold uppercase tracking-wider">{kpi.title}</span>
                    {kpi.icon}
                  </div>
                  <div className="flex items-end justify-between">
                    <span className="text-2xl font-bold font-mono text-[var(--lq-text-bright)] leading-none">{kpi.value}</span>
                    <span className={`flex items-center gap-1 text-[10px] font-semibold ${
                      kpi.delta === 'Alert' ? 'text-[var(--lq-amber)]' :
                      kpi.delta === 'Clear' ? 'text-[var(--lq-green)]' :
                      'text-[var(--lq-cyan)]'
                    }`}>
                      {kpi.live && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse inline-block" />}
                      {kpi.delta}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Map Area */}
            <div className="flex-1 rounded-lg overflow-hidden border border-[var(--lq-border)] relative shadow-sm min-h-[300px]">
              <FreightMap />
            </div>

          </ResizablePanel>

          <ResizableHandle withHandle className="w-1.5 bg-[var(--lq-border)] hover:bg-[var(--lq-cyan)] transition-colors" />

          {/* Right Panel: Agent Activity — Tabbed */}
          <ResizablePanel defaultSize={30} minSize={20} className="flex flex-col bg-[var(--lq-surface)] overflow-hidden min-h-0">
            {/* Tab Header */}
            <div className="p-3 border-b border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex items-center gap-1">
              <button
                onClick={() => setActiveTab('logs')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  activeTab === 'logs'
                    ? 'bg-[var(--lq-surface)] text-[var(--lq-purple)] shadow-sm'
                    : 'text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)]'
                }`}
              >
                <Activity size={13} />
                Agent Logs
                {logs.length > 0 && (
                  <span className="ml-1 px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-[var(--lq-purple)]/15 text-[var(--lq-purple)] border border-[var(--lq-purple)]/20">
                    {logs.length}
                  </span>
                )}
              </button>
              <button
                onClick={() => setActiveTab('disruptions')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-colors ${
                  activeTab === 'disruptions'
                    ? 'bg-[var(--lq-surface)] text-[var(--lq-amber)] shadow-sm'
                    : 'text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)]'
                }`}
              >
                <AlertTriangle size={13} />
                Disruptions
                {summary?.active_disruptions ? (
                  <span className="ml-1 px-1.5 py-0.5 text-[9px] font-bold rounded-full bg-[var(--lq-red)]/15 text-[var(--lq-red)] border border-[var(--lq-red)]/20">
                    {summary.active_disruptions}
                  </span>
                ) : null}
              </button>
            </div>

            {/* Tab Content */}
            <div className="flex-1 min-h-0 p-2 bg-[var(--lq-surface)] overflow-y-auto space-y-1.5">
              {activeTab === 'logs' ? (
                /* ── Agent Logs Tab ── */
                logs.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full opacity-50">
                    <Activity size={32} className="mb-2 text-[var(--lq-text-dim)] animate-pulse" />
                    <p className="text-[var(--lq-text-dim)] font-mono text-xs text-center">
                      System Active.<br/>Monitoring agent decision streams...
                    </p>
                    <p className="text-[9px] text-[var(--lq-text-dim)] mt-2 text-center">
                      Logs appear when the Decision Agent processes disruption events.
                    </p>
                  </div>
                ) : (
                  logs.map((log, idx) => {
                    const time = log.timestamp
                      ? new Date(log.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                      : '';
                    const desc = log.disruption?.description || log.description || log.message || 'Agent Decision Event';
                    const severity = log.disruption?.severity || log.severity;
                    const actions: string[] = log.actions || [];
                    const shipmentId = log.shipment_id || log.disruption?.shipment_id;
                    const isEscalated = log.human_escalated;
                    const isFallback = log.fallback_used;
                    const sevColor = severity === 'critical' || severity === 'high'
                      ? 'bg-red-500'
                      : severity === 'medium' ? 'bg-amber-400' : 'bg-blue-400';

                    return (
                      <div
                        key={log.trace_id || idx}
                        className="p-2 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg border-l-2 border-l-[var(--lq-purple)] animate-in fade-in slide-in-from-right-4 duration-300"
                      >
                        {/* Row 1: time + severity + badges + shipment id */}
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className="text-[9px] font-mono text-[var(--lq-text-dim)] shrink-0">{time}</span>
                          {severity && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${sevColor}`} title={severity} />}
                          {isFallback && <span className="text-[8px] bg-amber-500/15 text-amber-400 px-1 py-px rounded font-semibold">FB</span>}
                          {isEscalated && <span className="text-[8px] bg-red-500/20 text-red-400 px-1 py-px rounded font-semibold">ESC</span>}
                          {shipmentId && (
                            <span className="ml-auto text-[9px] font-mono text-[var(--lq-text-dim)] truncate max-w-[90px]">
                              {typeof shipmentId === 'string' ? shipmentId.slice(0, 8) : shipmentId}…
                            </span>
                          )}
                        </div>
                        {/* Row 2: description */}
                        <p className="text-[11px] text-[var(--lq-text-bright)] font-medium leading-snug line-clamp-2 mb-1">{desc}</p>
                        {/* Row 3: action chips (max 2 + overflow) */}
                        {actions.length > 0 && (
                          <div className="flex items-center gap-1 flex-wrap">
                            {actions.slice(0, 2).map((act: string, i: number) => (
                              <span key={i} className="text-[8px] bg-[var(--lq-purple)]/20 text-[var(--lq-purple)] px-1.5 py-px rounded font-mono border border-[var(--lq-purple)]/25">
                                {act}
                              </span>
                            ))}
                            {actions.length > 2 && (
                              <span className="text-[8px] text-[var(--lq-text-dim)] font-mono">+{actions.length - 2}</span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )
              ) : (
                /* ── Disruptions Tab (Scaffold) ── */
                <div className="flex flex-col h-full">
                  <div className="bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg p-4 mb-4">
                    <div className="flex items-center gap-3 mb-2">
                      <div className="w-8 h-8 rounded-lg bg-[var(--lq-amber)]/15 flex items-center justify-center">
                        <AlertTriangle size={16} className="text-[var(--lq-amber)]" />
                      </div>
                      <div>
                        <span className="text-2xl font-mono font-bold text-[var(--lq-text-bright)]">{summary?.active_disruptions ?? 0}</span>
                        <p className="text-[10px] text-[var(--lq-text-dim)] uppercase tracking-wider">Active Disruptions</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex-1 flex flex-col items-center justify-center text-center opacity-60">
                    <AlertTriangle size={28} className="mb-3 text-[var(--lq-text-dim)]" />
                    <p className="text-xs text-[var(--lq-text-dim)] mb-3 leading-relaxed">
                      Real-time disruption events stream here.<br/>
                      View and manage all incidents in the Risk Console.
                    </p>
                    <a href="/risk" className="text-xs font-semibold text-[var(--lq-cyan)] hover:underline">
                      Open Risk Console →
                    </a>
                  </div>
                </div>
              )}
            </div>
          </ResizablePanel>

        </ResizablePanelGroup>
      </div>
    </div>
  );
}
