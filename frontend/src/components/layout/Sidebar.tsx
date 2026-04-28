import { useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Package, AlertTriangle, Route, BarChart2, FileText, Settings, ChevronLeft, ChevronRight, CreditCard, Hexagon, Bot } from 'lucide-react';
import { useSidebarStore } from '@/stores/sidebar.store';
import { cn } from '@/lib/utils';

const NAV_SECTIONS = [
  {
    label: 'Operations',
    items: [
      { path: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard size={20} />, color: 'text-blue-500', border: 'border-blue-500' },
      { path: '/tracking', label: 'Shipments', icon: <Package size={20} />, color: 'text-cyan-500', border: 'border-cyan-500' },
      { path: '/risk', label: 'Risk & Alerts', icon: <AlertTriangle size={20} />, color: 'text-amber-500', border: 'border-amber-500' },
    ]
  },
  {
    label: 'Intelligence',
    items: [
      { path: '/routes', label: 'Route Optimizer', icon: <Route size={20} />, color: 'text-emerald-500', border: 'border-emerald-500' },
      { path: '/copilot', label: 'AI Copilot', icon: <Bot size={20} />, color: 'text-sky-500', border: 'border-sky-500' },
    ]
  },
  {
    label: 'Insights',
    items: [
      { path: '/analytics', label: 'Analytics', icon: <BarChart2 size={20} />, color: 'text-purple-500', border: 'border-purple-500' },
      { path: '/reports', label: 'Reports', icon: <FileText size={20} />, color: 'text-indigo-400', border: 'border-indigo-400' },
    ]
  },
  {
    label: 'Administration',
    items: [
      { path: '/billing', label: 'Billing', icon: <CreditCard size={20} />, color: 'text-teal-500', border: 'border-teal-500' },
      { path: '/settings', label: 'Settings', icon: <Settings size={20} />, color: 'text-slate-400', border: 'border-slate-400' },
    ]
  }
];

export function Sidebar() {
  const { expanded, toggle } = useSidebarStore();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggle]);

  return (
    <aside className={cn("lq-sidebar bg-[var(--lq-surface)] border-r border-[var(--lq-border)] flex flex-col transition-all duration-300", expanded ? "w-[var(--sidebar-w)]" : "w-16")}>
      <div className={cn("lq-sidebar-header h-[52px] flex items-center border-b border-[var(--lq-border)] shrink-0", expanded ? "justify-between px-4" : "justify-center px-0")}>
        {expanded ? (
          <div className="flex items-center gap-2 text-[var(--lq-text-bright)] font-bold text-lg">
            <Hexagon size={24} className="fill-[var(--lq-cyan)] text-[var(--lq-cyan)]" />
            <span>LogistiQ</span>
          </div>
        ) : (
          <div className="flex items-center justify-center">
            <Hexagon size={24} className="fill-[var(--lq-cyan)] text-[var(--lq-cyan)]" />
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-4 flex flex-col px-2 lq-nav-scroll">
        {NAV_SECTIONS.map((section, sIdx) => (
          <div key={section.label} className={cn("flex flex-col gap-1", sIdx > 0 && "mt-4")}>
            {expanded && (
              <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--lq-text-dim)] px-3 mb-1">
                {section.label}
              </span>
            )}
            {section.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 px-3 py-2 rounded-md transition-colors relative border-l-2",
                    isActive 
                      ? cn("bg-[var(--lq-surface-2)] text-[var(--lq-text-bright)] font-medium", expanded ? item.border : "border-transparent") 
                      : "border-transparent text-[var(--lq-text-dim)] hover:bg-[var(--lq-surface-2)] hover:text-[var(--lq-text)]"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span className={cn("shrink-0", (!isActive && expanded) && item.color)}>{item.icon}</span>
                    {expanded && <span className="whitespace-nowrap">{item.label}</span>}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      <div className="p-4 border-t border-[var(--lq-border)] flex justify-center shrink-0">
        <button onClick={toggle} className="p-1.5 rounded bg-[var(--lq-surface-2)] text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)] transition-colors">
          {expanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>
    </aside>
  );
}
