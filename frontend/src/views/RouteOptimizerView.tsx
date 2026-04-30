import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, CheckCircle2, Route, ArrowRight, Zap, Target, Leaf, Activity, Flame, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWebSocket } from '@/hooks/useWebSocket';
import { apiClient } from '@/lib/api';
import { toast } from 'sonner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RouteSegment {
  id: string;
  name: string;
  type: 'hub' | 'highway' | 'port' | 'rail';
  status: 'clear' | 'congested' | 'blocked';
  eta_mins: number;
}

interface RouteCandidate {
  id: string;
  solution_number: number;
  name: string;
  risk_score: number;
  cost: number;
  eta_hours: number;
  distance_km: number;
  carbon_delta: number;
  segments: RouteSegment[];
  routeIndex: number;  // 0-based index for apply-route API
}

interface DisruptionInfo {
  description: string;
  severity: string;
  event_type: string;
  lat?: number;
  lon?: number;
}

interface Bid {
  id: string;
  rank: number;
  carrier_name: string;
  price: number;
  eta_hours: number;
  confidence: number;
}

const MOCK_BIDS: Bid[] = [
  { id: 'b1', rank: 1, carrier_name: 'Mahindra Logistics', price: 47200, eta_hours: 24, confidence: 0.98 },
  { id: 'b2', rank: 2, carrier_name: 'Blue Dart Express', price: 48000, eta_hours: 26, confidence: 0.95 },
  { id: 'b3', rank: 3, carrier_name: 'TCI Freight', price: 46500, eta_hours: 28, confidence: 0.82 },
];

// ---------------------------------------------------------------------------
// Build route candidates from VRP results
// ---------------------------------------------------------------------------

function buildCandidatesFromVRP(data: any): RouteCandidate[] {
  const disruption = data.disruption || {};
  const altRoutes = data.alternate_routes || {};

  // Build baseline (current disrupted route)
  const candidates: RouteCandidate[] = [
    {
      id: 'disrupted-route',
      solution_number: 0,
      name: `Current Route (${disruption.event_type?.toUpperCase() || 'DISRUPTED'})`,
      risk_score: 0.95,
      cost: 0,
      eta_hours: 0,
      distance_km: 0,
      carbon_delta: 0,
      routeIndex: -1,
      segments: [
        { id: 's-origin', name: disruption.description?.split(' near')[0] || 'Origin', type: 'hub', status: 'clear', eta_mins: 0 },
        { id: 's-fire', name: `🔥 ${disruption.event_type || 'Fire'} Zone`, type: 'highway', status: 'blocked', eta_mins: 999 },
        { id: 's-dest', name: 'Destination', type: 'hub', status: 'clear', eta_mins: 0 },
      ],
    },
  ];

  // Parse alternatives from decision agent
  const routeEntries = Object.entries(altRoutes);
  if (routeEntries.length > 0) {
    routeEntries.forEach(([_shipId, routes]: [string, any]) => {
      if (!Array.isArray(routes)) return;
      routes.forEach((r: any, idx: number) => {
        candidates.push({
          id: r.route_id || `alt-${idx}`,
          solution_number: idx + 1,
          name: `Alternative ${idx + 1} (via ${r.via_waypoints?.join(', ') || 'detour'})`,
          risk_score: Math.max(0.05, 0.3 - idx * 0.08),
          cost: r.cost_inr || (45000 + idx * 3500),
          eta_hours: r.eta_hours ?? Math.round((r.duration_min || (180 + idx * 12)) / 60 * 10) / 10,
          distance_km: r.distance_km || (1200 + idx * 50),
          carbon_delta: -(1.2 + idx * 0.4),
          routeIndex: idx,
          segments: [
            { id: `s-${idx}-1`, name: 'Origin Hub', type: 'hub', status: 'clear', eta_mins: 0 },
            { id: `s-${idx}-2`, name: r.via_waypoints?.[0] || `Detour ${idx + 1}A`, type: 'highway', status: 'clear', eta_mins: Math.round((r.duration_min || 180) / 3) },
            { id: `s-${idx}-3`, name: r.via_waypoints?.[1] || `Detour ${idx + 1}B`, type: 'rail', status: 'clear', eta_mins: Math.round((r.duration_min || 180) / 3) },
            { id: `s-${idx}-4`, name: 'Destination', type: 'hub', status: 'clear', eta_mins: 0 },
          ],
        });
      });
    });
  } else {
    // Fallback: generate 2 smart alternatives based on disruption info
    for (let i = 0; i < 2; i++) {
      candidates.push({
        id: `fallback-alt-${i}`,
        solution_number: i + 1,
        name: i === 0 ? 'Highway Bypass (NH-7)' : 'Rail Multimodal (CONCOR)',
        risk_score: i === 0 ? 0.15 : 0.08,
        cost: i === 0 ? 48500 : 52000,
        eta_hours: i === 0 ? 26 : 32,
        distance_km: i === 0 ? 1380 : 1250,
        carbon_delta: i === 0 ? -0.8 : -2.4,
        routeIndex: i,
        segments: i === 0
          ? [
              { id: 'fb1-1', name: 'Origin Hub', type: 'hub', status: 'clear', eta_mins: 0 },
              { id: 'fb1-2', name: 'NH-7 Bypass', type: 'highway', status: 'clear', eta_mins: 420 },
              { id: 'fb1-3', name: 'Interchange', type: 'hub', status: 'clear', eta_mins: 180 },
              { id: 'fb1-4', name: 'Destination', type: 'hub', status: 'clear', eta_mins: 0 },
            ]
          : [
              { id: 'fb2-1', name: 'Origin Hub', type: 'hub', status: 'clear', eta_mins: 0 },
              { id: 'fb2-2', name: 'CONCOR Rail', type: 'rail', status: 'clear', eta_mins: 600 },
              { id: 'fb2-3', name: 'Rail Terminal', type: 'hub', status: 'clear', eta_mins: 120 },
              { id: 'fb2-4', name: 'Destination', type: 'hub', status: 'clear', eta_mins: 0 },
            ],
      });
    }
  }

  return candidates;
}

// ---------------------------------------------------------------------------
// Route Optimizer View
// ---------------------------------------------------------------------------

export default function RouteOptimizerView() {
  const navigate = useNavigate();
  const [candidates, setCandidates] = useState<RouteCandidate[]>([]);
  const [disruption, setDisruption] = useState<DisruptionInfo | null>(null);
  const [bids] = useState<Bid[]>(MOCK_BIDS);
  const [timer, setTimer] = useState(45);
  const [solveInfo, setSolveInfo] = useState<{ tokens: number; fallback: boolean } | null>(null);
  const [waiting, setWaiting] = useState(true);
  const [dispatching, setDispatching] = useState<string | null>(null); // route id being dispatched

  const handleDispatch = async (candidate: RouteCandidate) => {
    if (dispatching) return;
    setDispatching(candidate.id);
    try {
      const res = await apiClient.post('/simulation/disruption/apply-route', {
        route_index: candidate.routeIndex,
      });
      if (res.data.status === 'rerouted') {
        toast.success(
          `✅ Dispatched! Road shipment rerouted (${res.data.new_waypoints} waypoints). Map updating…`,
          { duration: 5000 },
        );
        // Navigate to dashboard so user sees the map update
        navigate('/');
      } else {
        toast.error(res.data.message ?? 'Dispatch failed — is simulation running?');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Network error';
      toast.error(`Dispatch failed: ${msg}`);
    } finally {
      setDispatching(null);
    }
  };

  // Connect to VRP results WS
  useWebSocket('vrp-results', (msg) => {
    if (msg.type === 'pong' || msg.type === 'heartbeat') return;
    if (msg.disruption || msg.alternate_routes) {
      const built = buildCandidatesFromVRP(msg);
      setCandidates(built);
      setDisruption(msg.disruption);
      setSolveInfo({ tokens: msg.gemini_tokens_used || 0, fallback: msg.fallback_used || false });
      setWaiting(false);
    }
  });

  useEffect(() => {
    const int = setInterval(() => setTimer(t => (t > 0 ? t - 1 : 0)), 1000);
    return () => clearInterval(int);
  }, []);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--lq-bg)] overflow-hidden">
      
      {/* VRP Solver Status Bar */}
      <div className="sticky top-0 z-10 bg-[var(--lq-surface)] border-b border-[var(--lq-border)] px-6 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 text-[var(--lq-cyan)]">
            <Play size={16} className={waiting ? 'animate-pulse' : ''} />
            <span className="text-sm font-semibold uppercase tracking-wider">
              {waiting ? 'VRP Solver Standby' : 'VRP Solver Active'}
            </span>
          </div>
          <div className="h-4 w-px bg-[var(--lq-border)]" />
          {solveInfo && (
            <div className="flex gap-4 text-xs font-mono text-[var(--lq-text-bright)]">
              <span>Tokens: <strong>{solveInfo.tokens.toLocaleString()}</strong></span>
              <span>Engine: <strong>{solveInfo.fallback ? 'VRP Fallback' : 'Gemini+VRP'}</strong></span>
            </div>
          )}
        </div>
        {!waiting && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--lq-text-bright)] uppercase tracking-wider">Status</span>
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 font-mono text-xs font-bold">
              <CheckCircle2 size={12} />
              Solved
            </div>
          </div>
        )}
      </div>

      <div className="p-6 overflow-y-auto flex-1" style={{ scrollbarWidth: 'thin', scrollbarColor: 'var(--lq-border) transparent' }}>

        {/* Disruption Alert Banner */}
        {disruption && (
          <div className="mb-6 bg-red-500/10 border border-red-500/25 rounded-xl p-4 flex items-start gap-4">
            <div className="w-10 h-10 bg-red-500/15 rounded-lg flex items-center justify-center shrink-0">
              <Flame size={20} className="text-red-400" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-red-400 mb-1">{disruption.severity.toUpperCase()} DISRUPTION DETECTED</h3>
              <p className="text-xs text-[var(--lq-text-bright)] leading-relaxed">{disruption.description}</p>
              {disruption.lat && disruption.lon && (
                <p className="text-[10px] text-[var(--lq-text-dim)] mt-1 font-mono">
                  Location: {disruption.lat.toFixed(4)}°N, {disruption.lon.toFixed(4)}°E
                </p>
              )}
            </div>
          </div>
        )}

        {/* Waiting State */}
        {waiting && candidates.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 opacity-60">
            <Loader2 size={40} className="text-[var(--lq-cyan)] animate-spin mb-4" />
            <h3 className="text-lg font-semibold text-[var(--lq-text-bright)] mb-2">VRP Solver Standing By</h3>
            <p className="text-sm text-[var(--lq-text-dim)] text-center max-w-md">
              Trigger a disruption from the <strong>Simulate</strong> dropdown in the top bar.<br/>
              Route alternatives will appear here in real-time.
            </p>
          </div>
        )}

        {/* Route Candidates */}
        {candidates.length > 0 && (
          <>
            <h2 className="text-xl font-semibold text-[var(--lq-text-bright)] mb-6 font-heading">Route Candidates</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
              {candidates.map((route) => {
                const isHighRisk = route.risk_score > 0.5;
                const isDisrupted = route.solution_number === 0;

                return (
                  <div key={route.id} className={cn("bg-[var(--lq-surface)] border rounded-xl overflow-hidden shadow-sm flex flex-col", isDisrupted ? "border-red-500/50 opacity-75" : isHighRisk ? "border-[var(--lq-amber)]/50" : "border-[var(--lq-border)]")}>
                    
                    <div className="p-4 border-b border-[var(--lq-border)] flex items-start justify-between">
                      <div>
                        <span className={cn("text-xs font-mono uppercase tracking-wider", isDisrupted ? 'text-red-400' : 'text-[var(--lq-text-bright)]')}>
                          {isDisrupted ? '⚠ Blocked' : `Solution #${route.solution_number}`}
                        </span>
                        <h3 className="text-lg font-semibold text-[var(--lq-text-bright)] mt-0.5">{route.name}</h3>
                      </div>
                      <div className="flex flex-col items-end">
                        <span className="text-[10px] uppercase text-[var(--lq-text-bright)] font-semibold mb-1">Risk Score</span>
                        <span className={cn("text-xl font-mono font-bold leading-none", isHighRisk ? "text-[var(--lq-amber)]" : "text-[var(--lq-green)]")}>
                          {route.risk_score.toFixed(2)}
                        </span>
                      </div>
                    </div>

                    <div className="grid grid-cols-3 divide-x divide-[var(--lq-border)] border-b border-[var(--lq-border)] bg-[var(--lq-bg)]">
                      <div className="p-3 text-center">
                        <span className="block text-[10px] text-[var(--lq-text-bright)] uppercase tracking-wider mb-1">Cost</span>
                        <span className="font-mono font-semibold text-[var(--lq-text-bright)]">₹{route.cost.toLocaleString()}</span>
                      </div>
                      <div className="p-3 text-center">
                        <span className="block text-[10px] text-[var(--lq-text-bright)] uppercase tracking-wider mb-1">ETA</span>
                        <span className="font-mono font-semibold text-[var(--lq-text-bright)]">{route.eta_hours}h</span>
                      </div>
                      <div className="p-3 text-center">
                        <span className="block text-[10px] text-[var(--lq-text-bright)] uppercase tracking-wider mb-1">Distance</span>
                        <span className="font-mono font-semibold text-[var(--lq-text-bright)]">{route.distance_km}km</span>
                      </div>
                    </div>

                    <div className="p-4 flex-1">
                      <span className="text-[10px] uppercase text-[var(--lq-text-bright)] font-semibold tracking-wider block mb-3">Path Segments</span>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {route.segments.map((seg, idx) => (
                          <div key={seg.id} className="flex items-center gap-1.5">
                            <div className={cn(
                              "px-2 py-1 rounded text-[10px] font-semibold border flex items-center gap-1",
                              seg.status === 'blocked' ? "bg-red-500/10 text-red-500 border-red-500/20 line-through" :
                              seg.status === 'congested' ? "bg-amber-500/10 text-amber-500 border-amber-500/20" :
                              "bg-[var(--lq-surface-2)] text-[var(--lq-text)] border-[var(--lq-border)]"
                            )}>
                              {seg.type === 'hub' ? <Target size={10} /> : <Route size={10} />}
                              {seg.name}
                            </div>
                            {idx < route.segments.length - 1 && <ArrowRight size={12} className="text-[var(--lq-text-dim)]" />}
                          </div>
                        ))}
                      </div>
                    </div>

                    {!isDisrupted && (
                      <div className="p-4 border-t border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex items-center justify-between">
                        <button className={cn(
                          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold border transition-colors",
                          route.carbon_delta < 0 
                            ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20 hover:bg-emerald-500/20" 
                            : "bg-[var(--lq-surface)] text-[var(--lq-text)] border-[var(--lq-border)] hover:bg-[var(--lq-border)]"
                        )}>
                          <Leaf size={14} />
                          {route.carbon_delta < 0 ? `${route.carbon_delta}t CO₂` : 'Green Mode'}
                        </button>
                        <button
                          id={`dispatch-route-${route.id}`}
                          onClick={() => handleDispatch(route)}
                          disabled={!!dispatching}
                          className="flex items-center gap-2 px-4 py-1.5 bg-[var(--lq-cyan)] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md text-sm font-semibold transition-opacity shadow-sm"
                        >
                          {dispatching === route.id
                            ? <><Loader2 size={14} className="animate-spin" /> Dispatching…</>
                            : <><Zap size={14} /> Dispatch</>
                          }
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Carrier Auction Panel */}
        {candidates.length > 0 && (
          <div className="bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-xl overflow-hidden shadow-sm">
            <div className="p-4 border-b border-[var(--lq-border)] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Activity className="text-[var(--lq-amber)]" size={18} />
                <h3 className="font-semibold text-[var(--lq-text-bright)]">Live Carrier Auction</h3>
                <span className="px-2 py-0.5 rounded bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] text-xs font-mono border border-[var(--lq-border)]">
                  /ws/carrier-auction
                </span>
              </div>
              <div className="flex items-center gap-2 text-[var(--lq-amber)] font-mono text-sm font-bold bg-amber-500/10 px-3 py-1 rounded border border-amber-500/20">
                00:00:{timer.toString().padStart(2, '0')}
              </div>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-[var(--lq-text-dim)] uppercase bg-[var(--lq-surface-2)] border-b border-[var(--lq-border)]">
                  <tr>
                    <th className="px-4 py-3 font-semibold">Rank</th>
                    <th className="px-4 py-3 font-semibold">Carrier</th>
                    <th className="px-4 py-3 font-semibold">Bid Price</th>
                    <th className="px-4 py-3 font-semibold">ETA (hrs)</th>
                    <th className="px-4 py-3 font-semibold">AI Confidence</th>
                    <th className="px-4 py-3 font-semibold text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--lq-border)]">
                  {bids.map((bid) => (
                    <tr key={bid.id} className={cn("transition-colors", bid.rank === 1 ? "bg-[var(--lq-green)]/5" : "hover:bg-[var(--lq-surface-2)]")}>
                      <td className="px-4 py-3 font-mono font-bold text-[var(--lq-text-bright)]">#{bid.rank}</td>
                      <td className="px-4 py-3 font-medium text-[var(--lq-text-bright)]">{bid.carrier_name}</td>
                      <td className="px-4 py-3 font-mono">₹{bid.price.toLocaleString()}</td>
                      <td className="px-4 py-3 font-mono">{bid.eta_hours}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-24 h-1.5 bg-[var(--lq-surface-2)] rounded-full overflow-hidden">
                            <div 
                              className={cn("h-full rounded-full", bid.confidence > 0.9 ? "bg-[var(--lq-green)]" : "bg-[var(--lq-amber)]")} 
                              style={{ width: `${bid.confidence * 100}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono text-[var(--lq-text-dim)]">{Math.round(bid.confidence * 100)}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button className={cn(
                          "px-3 py-1.5 rounded text-xs font-semibold border transition-colors",
                          bid.rank === 1 
                            ? "bg-[var(--lq-green)] text-white border-transparent shadow-sm hover:opacity-90" 
                            : "bg-[var(--lq-surface)] text-[var(--lq-text-bright)] border-[var(--lq-border)] hover:bg-[var(--lq-surface-2)]"
                        )}>
                          Accept
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
