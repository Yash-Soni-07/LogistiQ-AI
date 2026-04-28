import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  FileText, Download, Settings2, Clock, Loader2, CheckCircle2,
  AlertCircle, FileArchive, FileSpreadsheet,
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { useAuthStore } from '@/stores/auth.store';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';

// ── Types ──

interface ExportJob {
  id: string;
  name: string;
  dateRange: string;
  format: 'PDF' | 'CSV';
  status: 'generating' | 'ready' | 'error';
  timestamp: string;
  blob?: Blob;
  error?: string;
}

interface AnalyticsSummary {
  total_shipments: number;
  delivered: number;
  in_transit: number;
  delayed: number;
  cancelled: number;
  on_time_rate_pct: number;
  active_disruptions: number;
}

interface ShipmentItem {
  id: string;
  tracking_num: string;
  origin: string;
  destination: string;
  status: string;
  mode: string;
  risk_score: number;
  created_at: string;
}

// ── Report Generator ──

function buildCSV(summary: AnalyticsSummary, shipments: ShipmentItem[], reportType: string, dateRange: string): string {
  const lines: string[] = [];
  lines.push(`LogistiQ AI — ${reportType}`);
  lines.push(`Date Range: ${dateRange}`);
  lines.push(`Generated: ${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST`);
  lines.push('');
  lines.push('--- Summary ---');
  lines.push(`Total Shipments,${summary.total_shipments}`);
  lines.push(`Delivered,${summary.delivered}`);
  lines.push(`In Transit,${summary.in_transit}`);
  lines.push(`Delayed,${summary.delayed}`);
  lines.push(`Cancelled,${summary.cancelled}`);
  lines.push(`On-Time Rate,${summary.on_time_rate_pct}%`);
  lines.push(`Active Disruptions,${summary.active_disruptions}`);
  lines.push('');
  lines.push('--- Shipment Details ---');
  lines.push('Tracking #,Origin,Destination,Status,Mode,Risk Score,Created At');
  for (const s of shipments) {
    lines.push(`${s.tracking_num},${s.origin},${s.destination},${s.status},${s.mode},${s.risk_score},${s.created_at}`);
  }
  return lines.join('\n');
}

function buildPDF(summary: AnalyticsSummary, shipments: ShipmentItem[], reportType: string, dateRange: string, userName: string): Blob {
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
  const pageW = doc.internal.pageSize.getWidth();
  const ts = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST';

  // Header bar
  doc.setFillColor(13, 17, 23);
  doc.rect(0, 0, pageW, 32, 'F');
  doc.setTextColor(34, 211, 238);
  doc.setFontSize(18);
  doc.setFont('helvetica', 'bold');
  doc.text('LogistiQ.AI', 14, 14);
  doc.setFontSize(8);
  doc.setTextColor(148, 163, 184);
  doc.text('Intelligence & Command Report', 14, 20);
  doc.setFontSize(7);
  doc.text(`Generated: ${ts}  |  By: ${userName}`, 14, 27);

  // Report title
  let y = 42;
  doc.setTextColor(30, 41, 59);
  doc.setFontSize(14);
  doc.setFont('helvetica', 'bold');
  doc.text(reportType, 14, y);
  doc.setFontSize(9);
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(100, 116, 139);
  doc.text(dateRange, pageW - 14, y, { align: 'right' });

  // KPI summary table
  y += 8;
  autoTable(doc, {
    startY: y,
    head: [['Metric', 'Value']],
    body: [
      ['Total Shipments', String(summary.total_shipments)],
      ['Delivered', String(summary.delivered)],
      ['In Transit', String(summary.in_transit)],
      ['Delayed', String(summary.delayed)],
      ['Cancelled', String(summary.cancelled)],
      ['On-Time Rate', `${summary.on_time_rate_pct}%`],
      ['Active Disruptions', String(summary.active_disruptions)],
    ],
    theme: 'grid',
    headStyles: { fillColor: [13, 17, 23], textColor: [34, 211, 238], fontSize: 8 },
    bodyStyles: { fontSize: 8 },
    margin: { left: 14, right: 14 },
    tableWidth: 90,
  });

  // Shipment details table
  const finalY = (doc as any).lastAutoTable?.finalY ?? y + 60;
  autoTable(doc, {
    startY: finalY + 8,
    head: [['Tracking #', 'Origin', 'Destination', 'Status', 'Mode', 'Risk']],
    body: shipments.slice(0, 80).map(s => [
      s.tracking_num || s.id?.slice(0, 12) || '—',
      s.origin,
      s.destination,
      s.status,
      s.mode,
      String(s.risk_score ?? 0),
    ]),
    theme: 'striped',
    headStyles: { fillColor: [13, 17, 23], textColor: [226, 232, 240], fontSize: 7 },
    bodyStyles: { fontSize: 7 },
    margin: { left: 14, right: 14 },
  });

  // Footer
  const pages = doc.getNumberOfPages();
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setTextColor(148, 163, 184);
    doc.text(`LogistiQ AI — Confidential  |  Page ${i} of ${pages}`, pageW / 2, doc.internal.pageSize.getHeight() - 8, { align: 'center' });
  }

  return doc.output('blob');
}

// ── Download Button ──

function DownloadButton({ job }: { job: ExportJob }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (job.status === 'ready' && job.blob) {
      const objectUrl = URL.createObjectURL(job.blob);
      setUrl(objectUrl);
      return () => URL.revokeObjectURL(objectUrl);
    }
  }, [job]);

  if (job.status !== 'ready' || !url) return null;

  const ext = job.format === 'CSV' ? 'csv' : 'pdf';
  return (
    <a
      href={url}
      download={`LogistiQ_${job.name.replace(/ /g, '_')}_${job.dateRange.replace(/ /g, '_')}.${ext}`}
      className="p-2 text-[var(--lq-text-dim)] hover:text-[var(--lq-cyan)] hover:bg-[var(--lq-cyan-dim)] rounded-lg transition-colors shrink-0"
      title="Download"
    >
      <Download size={15} />
    </a>
  );
}

// ── Preview Paper ──

function PreviewPaper({ reportType, dateRange, userName, summary }: {
  reportType: string; dateRange: string; userName: string;
  summary: AnalyticsSummary | undefined;
}) {
  const ts = new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit' }) + ' IST';

  return (
    <div className="w-full max-w-[640px] aspect-[1/1.414] bg-white rounded-lg shadow-2xl mx-auto flex flex-col text-slate-900 overflow-hidden">
      {/* Header */}
      <div className="p-6 border-b border-slate-200 flex justify-between items-start">
        <div>
          <h2 className="text-xl font-bold text-cyan-600 mb-0.5">LogistiQ.AI</h2>
          <h3 className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">Intelligence & Command Report</h3>
        </div>
        <div className="text-right">
          <p className="text-[9px] text-slate-400 font-mono">Generated: {ts}</p>
          <p className="text-[9px] text-slate-400 font-mono mt-0.5">By: {userName}</p>
        </div>
      </div>

      {/* Body */}
      <div className="p-6 flex-1 flex flex-col gap-4 overflow-hidden">
        <div className="flex justify-between items-end">
          <h4 className="text-lg font-bold">{reportType}</h4>
          <span className="text-[10px] text-slate-500 font-mono bg-slate-100 px-2 py-0.5 rounded">{dateRange}</span>
        </div>
        <div className="h-px bg-slate-200 w-full" />

        {/* KPI Preview Cards */}
        {summary ? (
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Total', value: summary.total_shipments },
              { label: 'On-Time', value: `${summary.on_time_rate_pct}%` },
              { label: 'Disruptions', value: summary.active_disruptions },
            ].map((kpi, i) => (
              <div key={i} className="bg-slate-50 p-3 rounded border border-slate-100">
                <p className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">{kpi.label}</p>
                <p className="text-lg font-bold font-mono">{kpi.value}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-slate-50 p-3 rounded border border-slate-100 animate-pulse">
                <div className="h-2 w-1/2 bg-slate-200 rounded mb-2" />
                <div className="h-4 w-3/4 bg-slate-300 rounded" />
              </div>
            ))}
          </div>
        )}

        {/* Table Skeleton */}
        <div className="mt-2">
          <h5 className="text-xs font-bold text-slate-700 mb-2">Shipment Logs</h5>
          <div className="border border-slate-200 rounded overflow-hidden">
            <div className="bg-slate-900 h-7 flex items-center px-3">
              <div className="h-1.5 w-1/3 bg-slate-700 rounded" />
            </div>
            <div className="p-3 space-y-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="flex gap-3">
                  <div className="h-1.5 w-1/5 bg-slate-100 rounded" />
                  <div className="h-1.5 w-1/5 bg-slate-100 rounded" />
                  <div className="h-1.5 flex-1 bg-slate-100 rounded" />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Disruptions Footnote */}
        {summary && summary.active_disruptions > 0 && (
          <div className="mt-2">
            <h5 className="text-xs font-bold text-slate-700 mb-1.5">Active Disruptions</h5>
            <div className="bg-red-50 border border-red-100 rounded p-3">
              <p className="text-[10px] text-red-600 font-mono">{summary.active_disruptions} disruption(s) currently active — included in full export.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ──

export default function ReportsPage() {
  const { user } = useAuthStore();
  const [reportType, setReportType] = useState('SLA Performance');
  const [dateRange, setDateRange] = useState('Last 30 Days');
  const [format, setFormat] = useState<'PDF' | 'CSV'>('CSV');
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);

  const { data: summary } = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: async () => (await apiClient.get<AnalyticsSummary>('/analytics/summary')).data,
    staleTime: 30_000,
  });

  const generateReport = useCallback(async () => {
    setIsGenerating(true);
    const jobId = crypto.randomUUID();
    const newJob: ExportJob = {
      id: jobId, name: reportType, dateRange, format,
      status: 'generating',
      timestamp: new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }),
    };
    setJobs(prev => [newJob, ...prev]);

    try {
      // Fetch real data from backend
      const [summaryRes, shipmentsRes] = await Promise.all([
        apiClient.get<AnalyticsSummary>('/analytics/summary'),
        apiClient.get<{ items: ShipmentItem[] }>('/shipments?limit=200'),
      ]);

      let blob: Blob;
      if (format === 'CSV') {
        const csvContent = buildCSV(summaryRes.data, shipmentsRes.data.items, reportType, dateRange);
        blob = new Blob([csvContent], { type: 'text/csv' });
      } else {
        blob = buildPDF(summaryRes.data, shipmentsRes.data.items, reportType, dateRange, user?.full_name ?? 'LogistiQ Operator');
      }

      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'ready' as const, blob } : j));
    } catch (err) {
      setJobs(prev => prev.map(j => j.id === jobId ? { ...j, status: 'error' as const, error: 'Generation failed' } : j));
    } finally {
      setIsGenerating(false);
    }
  }, [reportType, dateRange, format]);

  return (
    <div className="w-full h-full flex bg-[var(--lq-bg)] text-[var(--lq-text-bright)] overflow-hidden">

      {/* Left Pane: Builder */}
      <div className="w-[420px] border-r border-[var(--lq-border)] bg-[var(--lq-surface)] flex flex-col shrink-0">
        <div className="p-5 border-b border-[var(--lq-border)]">
          <h1 className="text-xl font-semibold tracking-tight">Reporting Vault</h1>
          <p className="text-xs text-[var(--lq-text-dim)] mt-1">Configure and export detailed logistics audits.</p>
        </div>

        <div className="p-5 flex-1 overflow-y-auto space-y-6">
          {/* Builder Form */}
          <div className="space-y-5">
            <div className="flex items-center gap-2 mb-1">
              <Settings2 size={14} className="text-[var(--lq-text-dim)]" />
              <h2 className="text-[10px] font-bold uppercase tracking-widest text-[var(--lq-text-dim)]">Report Configuration</h2>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--lq-text)] mb-1.5">Report Type</label>
              <select
                value={reportType} onChange={e => setReportType(e.target.value)}
                className="w-full bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg p-2.5 text-sm text-[var(--lq-text-bright)] focus:outline-none focus:border-[var(--lq-cyan)] transition-colors appearance-none"
              >
                <option>SLA Performance</option>
                <option>Carbon Footprint Audit</option>
                <option>Cost vs Variance</option>
                <option>Disruption Mitigation</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--lq-text)] mb-1.5">Date Range</label>
              <select
                value={dateRange} onChange={e => setDateRange(e.target.value)}
                className="w-full bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-lg p-2.5 text-sm text-[var(--lq-text-bright)] focus:outline-none focus:border-[var(--lq-cyan)] transition-colors appearance-none"
              >
                <option>Last 7 Days</option>
                <option>Last 30 Days</option>
                <option>Last 90 Days</option>
                <option>Year to Date</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--lq-text)] mb-1.5">Format</label>
              <div className="flex gap-2">
                {(['CSV', 'PDF'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setFormat(f)}
                    className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                      format === f
                        ? 'bg-[var(--lq-cyan-dim)] text-[var(--lq-cyan)] border-[var(--lq-cyan)]'
                        : 'bg-[var(--lq-surface-2)] border-[var(--lq-border)] text-[var(--lq-text-dim)]'
                    }`}
                  >
                    {f === 'CSV' ? <span className="inline-flex items-center gap-1"><FileSpreadsheet size={12} />{f}</span> : <span className="inline-flex items-center gap-1"><FileText size={12} />{f}</span>}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={generateReport}
              disabled={isGenerating}
              className="w-full flex items-center justify-center gap-2 bg-[var(--lq-cyan)] hover:opacity-90 text-white px-4 py-2.5 rounded-lg font-semibold text-sm transition-opacity shadow-sm disabled:opacity-50"
            >
              {isGenerating ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />}
              {isGenerating ? 'Synthesizing…' : 'Generate Report'}
            </button>
          </div>

          <div className="h-px bg-[var(--lq-border)]" />

          {/* Export Queue */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex items-center gap-2 mb-3">
              <FileArchive size={14} className="text-[var(--lq-text-dim)]" />
              <h2 className="text-[10px] font-bold uppercase tracking-widest text-[var(--lq-text-dim)]">Recent Exports</h2>
            </div>

            <div className="space-y-2">
              {jobs.length === 0 ? (
                <p className="text-center text-[var(--lq-text-dim)] text-xs py-8">No recent exports.</p>
              ) : (
                jobs.map(job => (
                  <div key={job.id} className={`bg-[var(--lq-surface-2)] border rounded-lg p-3 flex items-center justify-between transition-colors ${
                    job.status === 'error' ? 'border-red-500/40' : 'border-[var(--lq-border)] hover:border-[var(--lq-border-hover)]'
                  }`}>
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`p-1.5 rounded-lg ${job.status === 'ready' ? 'bg-emerald-500/10' : job.status === 'error' ? 'bg-red-500/10' : 'bg-[var(--lq-surface)]'}`}>
                        {job.status === 'generating' ? <Loader2 size={14} className="text-[var(--lq-text-dim)] animate-spin" /> :
                          job.status === 'error' ? <AlertCircle size={14} className="text-[var(--lq-red)]" /> :
                            <CheckCircle2 size={14} className="text-[var(--lq-green)]" />}
                      </div>
                      <div className="min-w-0">
                        <p className={`text-sm font-semibold truncate ${job.status === 'error' ? 'text-[var(--lq-red)]' : ''}`}>
                          {job.status === 'error' ? 'Generation Error' : job.name}
                        </p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <Clock size={10} className="text-[var(--lq-text-dim)]" />
                          <span className="text-[10px] text-[var(--lq-text-dim)] font-mono truncate">
                            {job.status === 'error' ? job.error : `${job.timestamp} · ${job.format}`}
                          </span>
                        </div>
                      </div>
                    </div>
                    <DownloadButton job={job} />
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right Pane: Preview */}
      <div className="flex-1 flex flex-col overflow-hidden relative bg-[var(--lq-bg)]">
        <div className="p-3 border-b border-[var(--lq-border)] bg-[var(--lq-surface)] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--lq-green)]" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--lq-text-dim)]">Live Preview</span>
          </div>
          <span className="text-[10px] font-mono text-[var(--lq-text-dim)]">A4 Document Scale</span>
        </div>
        <div className="flex-1 overflow-y-auto p-8 flex items-start justify-center">
          <PreviewPaper
            reportType={reportType}
            dateRange={dateRange}
            userName={user?.full_name ?? 'Operations Commander'}
            summary={summary}
          />
        </div>
      </div>
    </div>
  );
}
