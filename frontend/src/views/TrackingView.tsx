import { useState, useMemo, useRef } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Search, Download, ChevronDown, Copy, X, Ship, Truck, Plane, Train, RefreshCw } from 'lucide-react';
import { Map as MapGL, Marker } from 'react-map-gl/maplibre';
import { apiClient } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useWebSocket } from '@/hooks/useWebSocket';


// ---------------------------------------------------------------------------
// Types & Constants
// ---------------------------------------------------------------------------

interface ShipmentRow {
  id: string;
  tracking_num: string;
  origin: string;
  destination: string;
  carrier: string;
  mode: 'sea' | 'air' | 'road' | 'rail';
  sector: string;
  status: 'in_transit' | 'delayed' | 'rerouted' | 'delivered' | 'at_risk' | 'pending';
  eta: string;
  risk_score: number;
  agent_action?: string;
  lat?: number;
  lng?: number;
}

const SECTORS = ['automotive', 'pharma', 'tech', 'retail', 'cold_chain', 'food', 'electronics', 'textiles', 'agriculture'];

const MAP_STYLE =
  (import.meta.env.VITE_STADIA_MAPS_STYLE as string | undefined) ??
  'https://tiles.stadiamaps.com/styles/alidade_smooth_dark.json';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ModeIcon({ mode }: { mode: ShipmentRow['mode'] }) {
  switch (mode) {
    case 'sea': return <Ship size={14} className="text-blue-400" />;
    case 'air': return <Plane size={14} className="text-sky-300" />;
    case 'rail': return <Train size={14} className="text-amber-500" />;
    case 'road':
    default: return <Truck size={14} className="text-slate-400" />;
  }
}

function StatusChip({ status }: { status: ShipmentRow['status'] }) {
  let colorClass = 'bg-[var(--lq-surface-2)] text-[var(--lq-text-bright)] border-[var(--lq-border)]';
  if (status === 'in_transit') colorClass = 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20';
  if (status === 'rerouted') colorClass = 'bg-violet-500/10 text-violet-400 border-violet-500/20';
  if (status === 'delayed') colorClass = 'bg-red-500/10 text-red-400 border-red-500/20';
  if (status === 'at_risk') colorClass = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
  if (status === 'delivered') colorClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';

  return (
    <span className={cn('px-2 py-0.5 rounded-full text-[11px] font-medium border uppercase tracking-wider', colorClass)}>
      {status.replace('_', ' ')}
    </span>
  );
}

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text);
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

export function TrackingView() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sectorFilters, setSectorFilters] = useState<string[]>([]);
  const [sectorDropdownOpen, setSectorDropdownOpen] = useState(false);
  const [selectedRow, setSelectedRow] = useState<ShipmentRow | null>(null);

  const queryClient = useQueryClient();

  useWebSocket('shipments', (message: any) => {
    if (message && typeof message === 'object') {
      if (['fire_event', 'fire_cleared', 'simulation_started'].includes(message.type)) {
        queryClient.invalidateQueries({ queryKey: ['shipments', 'table'] });
      }
    }
  });

  // ── Data Fetching ────────────────────────────────────────────────────────
  const { data: shipments = [], isLoading, refetch } = useQuery({
    queryKey: ['shipments', 'table'],
    queryFn: async () => {
      // Fetch up to 2000 for client-side virtual table demo
      const res = await apiClient.get<{ items: any[] }>('/shipments?limit=2000');
      
      const mappedItems = res.data.items.map(item => ({
        ...item,
        lat: item.current_lat,
        lng: item.current_lon
      })) as ShipmentRow[];
      
      // Keep selectedRow updated if it's currently selected
      setSelectedRow(prev => {
        if (!prev) return prev;
        const fresh = mappedItems.find(s => s.id === prev.id);
        return fresh ? { ...fresh } : prev;
      });
      
      return mappedItems;
    },
  });

  // ── Client-side Filtering ────────────────────────────────────────────────
  const filteredData = useMemo(() => {
    return shipments.filter((s) => {
      if (statusFilter !== 'all' && s.status !== statusFilter) return false;
      if (sectorFilters.length > 0 && !sectorFilters.includes(s.sector)) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          (s.tracking_num ?? '').toLowerCase().includes(q) ||
          (s.origin ?? '').toLowerCase().includes(q) ||
          (s.destination ?? '').toLowerCase().includes(q) ||
          (s.carrier ?? '').toLowerCase().includes(q) ||
          (s.id ?? '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [shipments, search, statusFilter, sectorFilters]);

  // ── Virtualization ───────────────────────────────────────────────────────
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: filteredData.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48, // Fixed row height 48px
    overscan: 10,
  });

  const toggleSector = (sector: string) => {
    setSectorFilters(prev => 
      prev.includes(sector) ? prev.filter(s => s !== sector) : [...prev, sector]
    );
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--lq-bg)] text-[var(--lq-text-bright)] font-sans overflow-hidden">
      
      {/* ── Top Bar ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--lq-border)] bg-[var(--lq-surface)] shrink-0">
        <div className="flex items-center gap-4 flex-1">
          {/* Search */}
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-2 text-slate-500" size={14} />
            <input
              type="text"
              placeholder="Search shipments..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-[var(--lq-bg)] border border-[var(--lq-border)] text-sm rounded-md pl-8 pr-3 py-1.5 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all font-mono"
            />
          </div>

          {/* Status Chips */}
          <div className="flex items-center gap-2 bg-[var(--lq-bg)] p-1 rounded-md border border-[var(--lq-border)]">
            {['all', 'in_transit', 'at_risk', 'rerouted', 'delayed'].map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium uppercase tracking-wider transition-colors",
                  statusFilter === f ? "bg-[var(--lq-surface-2)] text-[var(--lq-text-bright)]" : "text-[var(--lq-text-dim)] hover:text-[var(--lq-text)]"
                )}
              >
                {f.replace('_', ' ')}
              </button>
            ))}
          </div>

          {/* Sector Dropdown */}
          <div className="relative">
            <button 
              onClick={() => setSectorDropdownOpen(!sectorDropdownOpen)}
              className="flex items-center gap-2 px-3 py-1.5 bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded-md text-sm hover:border-[var(--lq-border-hover)] transition-colors"
            >
              <span className="text-[var(--lq-text-dim)]">Sector:</span>
              <span className="font-medium text-[var(--lq-text-bright)]">
                {sectorFilters.length === 0 ? 'All' : `${sectorFilters.length} selected`}
              </span>
              <ChevronDown size={14} className="text-slate-500" />
            </button>
            
            {sectorDropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-48 bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-md shadow-xl z-50 py-1">
                {SECTORS.map(s => (
                  <label key={s} className="flex items-center gap-2 px-3 py-2 hover:bg-[var(--lq-surface-2)] cursor-pointer text-sm capitalize">
                    <input 
                      type="checkbox" 
                      checked={sectorFilters.includes(s)}
                      onChange={() => toggleSector(s)}
                      className="rounded border-[var(--lq-border)] bg-[var(--lq-surface-2)] text-[var(--lq-cyan)] focus:ring-cyan-500/20"
                    />
                    {s.replace('_', ' ')}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Export */}
        <button
          onClick={() => {
            const header = 'ID,Tracking #,Origin,Destination,Mode,Sector,Status,Risk Score';
            const rows = filteredData.map(s => `${s.id},${s.tracking_num ?? ''},${s.origin},${s.destination},${s.mode},${s.sector},${s.status},${s.risk_score}`);
            const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = 'shipments_export.csv'; a.click();
            URL.revokeObjectURL(url);
          }}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--lq-surface-2)] hover:opacity-80 text-[var(--lq-text-bright)] rounded-md text-sm transition-colors border border-[var(--lq-border)]"
        >
          <Download size={14} />
          <span>Export CSV</span>
        </button>
      </div>

      {/* ── Table Header ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-[140px_minmax(200px,1fr)_120px_100px_120px_100px_120px_1fr_80px] gap-4 px-4 py-3 bg-[var(--lq-surface)] border-b border-[var(--lq-border)] text-xs font-semibold text-[var(--lq-text-dim)] uppercase tracking-wider shrink-0">
        <div>Shipment ID</div>
        <div>Route</div>
        <div>Carrier</div>
        <div>Sector</div>
        <div>Status</div>
        <div>ETA</div>
        <div>Risk Score</div>
        <div>Agent Action</div>
        <div className="text-right">Actions</div>
      </div>

      {/* ── Virtualized Table Body ───────────────────────────────────────── */}
      <div 
        ref={parentRef} 
        className="flex-1 overflow-auto min-h-0 relative"
      >
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="lq-spinner" />
          </div>
        ) : filteredData.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-slate-500">
            No shipments found matching filters.
          </div>
        ) : (
          <div
            style={{
              height: `${rowVirtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const row = filteredData[virtualRow.index];
              const isHighRisk = row.risk_score > 0.7;
              
              return (
                <div
                  key={row.id}
                  className="absolute top-0 left-0 w-full flex items-center grid grid-cols-[140px_minmax(200px,1fr)_120px_100px_120px_100px_120px_1fr_80px] gap-4 px-4 border-b border-[var(--lq-border)] hover:bg-[var(--lq-surface-2)] transition-colors text-sm group cursor-pointer"
                  style={{
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  onClick={() => setSelectedRow(row)}
                >
                  {/* ID */}
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-cyan-400 text-xs">{row.tracking_num || row.id.slice(0, 12)}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); copyToClipboard(row.tracking_num || row.id); }}
                      className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-cyan-400 transition-all"
                    >
                      <Copy size={12} />
                    </button>
                  </div>

                  {/* Route */}
                  <div className="flex items-center gap-2 truncate text-[var(--lq-text-bright)]">
                    <span className="truncate" title={row.origin}>{row.origin}</span>
                    <span className="text-[var(--lq-text-dim)]">→</span>
                    <span className="truncate" title={row.destination}>{row.destination}</span>
                  </div>

                  {/* Carrier + Mode */}
                  <div className="flex items-center gap-2 text-[var(--lq-text)] truncate">
                    <ModeIcon mode={row.mode} />
                    <span className="truncate">{row.carrier || 'Unknown'}</span>
                  </div>

                  {/* Sector */}
                  <div className="text-[var(--lq-text)] capitalize text-xs">
                    {row.sector.replace('_', ' ')}
                  </div>

                  {/* Status */}
                  <div>
                    <StatusChip status={row.status} />
                  </div>

                  {/* ETA */}
                  <div className={cn("text-[var(--lq-text-bright)] text-xs font-mono", row.status === 'delayed' && "text-[var(--lq-red)]")}>
                    {row.eta ? new Date(row.eta).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '—'}
                  </div>

                  {/* Risk Score */}
                  <div className="flex items-center gap-2">
                    <div className="w-12 h-1.5 bg-[var(--lq-surface-2)] rounded-full overflow-hidden border border-[var(--lq-border)]">
                      <div 
                        className={cn("h-full rounded-full", isHighRisk ? "bg-red-500" : row.risk_score > 0.4 ? "bg-amber-500" : "bg-emerald-500")}
                        style={{ width: `${Math.max(5, row.risk_score * 100)}%` }}
                      />
                    </div>
                    <span className={cn("text-xs font-mono", isHighRisk ? "text-[var(--lq-red)]" : "text-[var(--lq-text-dim)]")}>
                      {(row.risk_score * 100).toFixed(0)}
                    </span>
                  </div>

                  {/* Agent Action */}
                  <div className="truncate text-xs text-[var(--lq-text)]">
                    {row.agent_action || <span className="text-[var(--lq-text-dim)]">No interventions</span>}
                  </div>

                  {/* Actions */}
                  <div className="text-right">
                    <button className="text-xs text-cyan-500 hover:text-cyan-400 font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                      Details
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Detail Side Sheet ────────────────────────────────────────────── */}
      {selectedRow && (
        <>
          {/* Backdrop */}
          <div 
            className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 transition-opacity"
            onClick={() => setSelectedRow(null)}
          />
          
          {/* Sheet */}
          <aside className="fixed top-0 right-0 h-full w-[480px] bg-[var(--lq-surface)] border-l border-[var(--lq-border)] shadow-2xl z-50 flex flex-col lq-sheet animate-in slide-in-from-right duration-200">
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-[var(--lq-border)]">
              <div>
                <p className="text-sm text-[var(--lq-text-dim)] uppercase tracking-widest mb-1">Shipment Profile</p>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-mono text-[var(--lq-text-bright)]">{selectedRow.tracking_num || selectedRow.id.slice(0, 12)}</h2>
                  <StatusChip status={selectedRow.status} />
                </div>
              </div>
              <button 
                onClick={() => setSelectedRow(null)}
                className="p-2 hover:bg-[var(--lq-surface-2)] rounded-md text-[var(--lq-text-dim)] transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-8">
              {/* Info Grid */}
              <div className="grid grid-cols-2 gap-y-6 gap-x-4">
                <div>
                  <p className="text-xs text-[var(--lq-text-dim)] mb-1">Origin</p>
                  <p className="text-sm text-[var(--lq-text-bright)] font-medium">{selectedRow.origin}</p>
                </div>
                <div>
                  <p className="text-xs text-[var(--lq-text-dim)] mb-1">Destination</p>
                  <p className="text-sm text-[var(--lq-text-bright)] font-medium">{selectedRow.destination}</p>
                </div>
                <div>
                  <p className="text-xs text-[var(--lq-text-dim)] mb-1">Carrier / Mode</p>
                  <p className="text-sm text-[var(--lq-text-bright)] flex items-center gap-2">
                    <ModeIcon mode={selectedRow.mode} />
                    {selectedRow.carrier || 'N/A'}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[var(--lq-text-dim)] mb-1">Sector</p>
                  <p className="text-sm text-[var(--lq-text-bright)] capitalize">{selectedRow.sector.replace('_', ' ')}</p>
                </div>
              </div>

              {/* Position Map (Mini MapLibre Instance) */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--lq-text-bright)] tracking-wide">Current Position</h3>
                <div className="h-48 w-full rounded-lg overflow-hidden border border-[var(--lq-border)] bg-[var(--lq-surface-2)] relative">
                  <MapGL
                    key={selectedRow.id}
                    initialViewState={{
                      longitude: selectedRow.lng || 79,
                      latitude: selectedRow.lat || 20,
                      zoom: selectedRow.lat ? 5 : 3
                    }}
                    mapStyle={MAP_STYLE}
                    interactive={true}
                    attributionControl={false}
                  >
                    {selectedRow.lat && selectedRow.lng && (
                      <Marker longitude={selectedRow.lng} latitude={selectedRow.lat}>
                        <div className="relative flex items-center justify-center">
                          <div className="absolute w-6 h-6 bg-[var(--lq-cyan)]/30 rounded-full animate-ping" />
                          <div className="w-3 h-3 bg-cyan-400 rounded-full shadow-[0_0_10px_rgba(34,211,238,0.8)] border-2 border-[#0a0d16] relative z-10" />
                        </div>
                      </Marker>
                    )}
                  </MapGL>
                  <button 
                    onClick={() => refetch()}
                    disabled={isLoading}
                    title="Refresh Location"
                    className="absolute top-2 right-2 p-1.5 bg-black/60 hover:bg-black/90 backdrop-blur rounded border border-[var(--lq-border)] text-[var(--lq-text-dim)] hover:text-white transition-colors"
                  >
                    <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
                  </button>
                  {(!selectedRow.lat || !selectedRow.lng) && (
                    <div className="absolute inset-0 flex items-center justify-center backdrop-blur-sm pointer-events-none" style={{ backgroundColor: 'color-mix(in srgb, var(--lq-surface-2) 80%, transparent)' }}>
                      <span className="text-xs text-[var(--lq-text-dim)]">Live coordinates unavailable</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Risk Breakdown */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-[var(--lq-text-bright)] tracking-wide">Risk Assessment</h3>
                <div className="p-4 bg-[var(--lq-surface-2)] rounded-lg border border-[var(--lq-border)] space-y-4">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--lq-text)]">Overall Score</span>
                    <span className={cn("font-mono font-bold", selectedRow.risk_score > 0.7 ? "text-[var(--lq-red)]" : "text-[var(--lq-text-bright)]")}>
                      {(selectedRow.risk_score * 100).toFixed(0)} / 100
                    </span>
                  </div>
                  <div className="space-y-2">
                    {/* Simulated breakdown bars */}
                    <div className="flex items-center gap-3">
                      <span className="text-xs w-16 text-[var(--lq-text-dim)]">Weather</span>
                      <div className="flex-1 h-1.5 bg-[var(--lq-border)] rounded-full overflow-hidden">
                        <div className="h-full bg-[var(--lq-cyan)] rounded-full" style={{ width: `${Math.random() * 40 + 10}%` }} />
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs w-16 text-[var(--lq-text-dim)]">Security</span>
                      <div className="flex-1 h-1.5 bg-[var(--lq-border)] rounded-full overflow-hidden">
                        <div className="h-full bg-[var(--lq-amber)] rounded-full" style={{ width: `${Math.random() * 30 + 5}%` }} />
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs w-16 text-[var(--lq-text-dim)]">Network</span>
                      <div className="flex-1 h-1.5 bg-[var(--lq-border)] rounded-full overflow-hidden">
                        <div className="h-full bg-[var(--lq-red)] rounded-full" style={{ width: `${Math.random() * 80 + 20}%` }} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Decision History */}
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-[var(--lq-text-bright)] tracking-wide">Agent Interventions</h3>
                {selectedRow.agent_action ? (
                  <div className="relative pl-4 border-l border-[var(--lq-border)] space-y-4">
                    <div className="relative">
                      <div className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-[var(--lq-cyan)] border border-[var(--lq-surface)]" />
                      <p className="text-xs text-[var(--lq-text-dim)] mb-1">System detected high risk</p>
                      <div className="p-3 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded text-sm text-[var(--lq-text-bright)] font-mono">
                        {selectedRow.agent_action}
                      </div>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-[var(--lq-text-dim)] italic">No AI interventions recorded for this shipment.</p>
                )}
              </div>

            </div>
          </aside>
        </>
      )}
    </div>
  );
}

export default TrackingView;
