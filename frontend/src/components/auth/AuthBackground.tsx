/**
 * AuthBackground.tsx
 * ---
 * Immersive logistics control-tower background for auth pages (Login / Register).
 *
 * Four visual layers (back to front):
 *   1. Radial gradient atmosphere — cyan glow bottom-left, violet glow top-right
 *   2. Dot-grid overlay — subtle pattern at 3% opacity
 *   3. Animated SVG route network — abstract highway corridors with pulse animation
 *   4. Floating metric badges — frosted-glass cards with staggered float animation
 *
 * Technical constraints:
 *   - position: fixed; inset: 0; z-index: 0; pointer-events: none
 *   - Uses only --lq-* CSS variables for automatic light/dark theme support
 *   - All animations are inline <style> — no global CSS changes
 *   - No new npm packages
 */

export default function AuthBackground() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        overflow: 'hidden',
      }}
      aria-hidden="true"
    >
      {/* ── Inline keyframes ──────────────────────────────────── */}
      <style>{`
        @keyframes authPulse {
          0%, 100% { stroke-opacity: 0.08; }
          50%      { stroke-opacity: 0.22; }
        }
        @keyframes authPulseBright {
          0%, 100% { stroke-opacity: 0.12; }
          50%      { stroke-opacity: 0.32; }
        }
        @keyframes authPacket {
          0%   { offset-distance: 0%; opacity: 0; }
          10%  { opacity: 1; }
          90%  { opacity: 1; }
          100% { offset-distance: 100%; opacity: 0; }
        }
        @keyframes authFloat {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-6px); }
        }
        @keyframes authDotPulse {
          0%, 100% { opacity: 0.6; }
          50%      { opacity: 1; }
        }
      `}</style>

      {/* ── Layer 1 — Radial gradient atmosphere ────────────── */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: [
            'radial-gradient(ellipse 60% 50% at 15% 85%, var(--lq-cyan-glow) 0%, transparent 70%)',
            'radial-gradient(ellipse 50% 40% at 85% 15%, rgba(124,58,237,0.05) 0%, transparent 70%)',
          ].join(', '),
        }}
      />

      {/* ── Layer 2 — Dot-grid overlay ─────────────────────── */}
      <svg
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      >
        <defs>
          <pattern id="auth-dot-grid" x="0" y="0" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="12" cy="12" r="0.8" fill="var(--lq-text-dim)" fillOpacity="0.06" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#auth-dot-grid)" />
      </svg>

      {/* ── Layer 3 — Animated SVG route network ───────────── */}
      <svg
        viewBox="0 0 1200 800"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      >
        {/* -- Route nodes (hub cities) -- */}
        {ROUTE_NODES.map((node) => (
          <circle
            key={node.id}
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill="var(--lq-cyan)"
            fillOpacity={0.15}
            stroke="var(--lq-cyan)"
            strokeOpacity={0.2}
            strokeWidth={0.5}
          />
        ))}

        {/* -- Route paths (highway corridors) -- */}
        {ROUTE_PATHS.map((rp) => (
          <path
            key={rp.id}
            d={rp.d}
            fill="none"
            stroke="var(--lq-cyan)"
            strokeWidth={rp.w}
            strokeLinecap="round"
            style={{
              animation: `${rp.bright ? 'authPulseBright' : 'authPulse'} ${rp.dur}s ease-in-out infinite`,
              animationDelay: `${rp.delay}s`,
            }}
          />
        ))}

        {/* -- Traveling data packets -- */}
        {DATA_PACKETS.map((pkt) => (
          <circle
            key={pkt.id}
            r={pkt.r}
            fill="var(--lq-cyan)"
            fillOpacity={0.6}
            style={{
              offsetPath: `path("${pkt.path}")`,
              animation: `authPacket ${pkt.dur}s linear infinite`,
              animationDelay: `${pkt.delay}s`,
            }}
          />
        ))}
      </svg>

      {/* ── Layer 4 — Floating metric badges ───────────────── */}
      {METRIC_BADGES.map((badge) => (
        <div
          key={badge.id}
          className="hidden md:flex"
          style={{
            position: 'absolute',
            ...badge.pos,
            display: undefined,   // let className handle
            alignItems: 'center',
            gap: '8px',
            padding: '8px 14px',
            borderRadius: '10px',
            border: '1px solid var(--lq-border)',
            background: 'var(--lq-surface)',
            opacity: 0.75,
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            boxShadow: '0 4px 24px rgba(0,0,0,0.12)',
            fontFamily: 'var(--lq-font-mono)',
            fontSize: '11px',
            color: 'var(--lq-text)',
            whiteSpace: 'nowrap',
            animation: `authFloat 4s ease-in-out infinite`,
            animationDelay: `${badge.delay}s`,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: badge.dotColor,
              flexShrink: 0,
              animation: 'authDotPulse 2s ease-in-out infinite',
            }}
          />
          <span>{badge.label}</span>
        </div>
      ))}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   Static data — kept outside the component to avoid
   re-creation on every render.
   ──────────────────────────────────────────────────────────── */

/** Abstract hub nodes — loosely inspired by Indian logistics hubs */
const ROUTE_NODES = [
  { id: 'n1', x: 580, y: 280, r: 4 },   // Delhi
  { id: 'n2', x: 460, y: 500, r: 3.5 },  // Mumbai
  { id: 'n3', x: 680, y: 600, r: 3 },    // Hyderabad
  { id: 'n4', x: 750, y: 720, r: 3.5 },  // Bangalore
  { id: 'n5', x: 820, y: 760, r: 2.5 },  // Chennai
  { id: 'n6', x: 720, y: 350, r: 2.5 },  // Lucknow
  { id: 'n7', x: 850, y: 420, r: 2.5 },  // Kolkata
  { id: 'n8', x: 370, y: 380, r: 2.5 },  // Ahmedabad
  { id: 'n9', x: 520, y: 650, r: 2 },    // Pune
] as const;

/** Abstract highway corridors */
const ROUTE_PATHS = [
  // NH-44 corridor (Delhi → Bangalore)
  { id: 'p1', d: 'M580,280 C580,380 560,440 460,500',                   w: 1.2, dur: 10, delay: 0,   bright: true },
  { id: 'p2', d: 'M460,500 C520,540 600,560 680,600',                    w: 1.0, dur: 12, delay: 1,   bright: false },
  { id: 'p3', d: 'M680,600 C710,650 730,680 750,720',                    w: 1.0, dur: 11, delay: 0.5, bright: false },
  // NH-48 corridor (Delhi → Ahmedabad → Mumbai)
  { id: 'p4', d: 'M580,280 C520,310 440,340 370,380',                    w: 1.1, dur: 9,  delay: 2,   bright: true },
  { id: 'p5', d: 'M370,380 C400,430 430,470 460,500',                    w: 0.8, dur: 10, delay: 1.5, bright: false },
  // Eastern corridor (Delhi → Lucknow → Kolkata)
  { id: 'p6', d: 'M580,280 C630,300 670,320 720,350',                    w: 0.9, dur: 11, delay: 0.8, bright: false },
  { id: 'p7', d: 'M720,350 C770,370 810,390 850,420',                    w: 0.8, dur: 13, delay: 2.5, bright: false },
  // Southern spokes
  { id: 'p8', d: 'M750,720 C780,740 800,750 820,760',                    w: 0.7, dur: 8,  delay: 1,   bright: false },
  { id: 'p9', d: 'M460,500 C480,570 500,620 520,650',                    w: 0.7, dur: 9,  delay: 3,   bright: false },
  // Cross-links
  { id: 'p10', d: 'M850,420 C820,500 780,560 680,600',                   w: 0.6, dur: 14, delay: 1.2, bright: false },
  { id: 'p11', d: 'M520,650 Q600,660 680,600',                           w: 0.6, dur: 10, delay: 2.8, bright: false },
  // Faint long-distance arcs
  { id: 'p12', d: 'M370,380 Q250,550 460,500',                           w: 0.5, dur: 15, delay: 4,   bright: false },
  { id: 'p13', d: 'M580,280 Q900,300 850,420',                           w: 0.5, dur: 16, delay: 3.5, bright: false },
] as const;

/** Animated dots that travel along specific route paths */
const DATA_PACKETS = [
  { id: 'dp1', path: 'M580,280 C580,380 560,440 460,500',                r: 2.5, dur: 6,  delay: 0 },
  { id: 'dp2', path: 'M460,500 C520,540 600,560 680,600',                r: 2,   dur: 7,  delay: 3 },
  { id: 'dp3', path: 'M580,280 C520,310 440,340 370,380',                r: 2,   dur: 5,  delay: 1.5 },
  { id: 'dp4', path: 'M680,600 C710,650 730,680 750,720',                r: 2,   dur: 4,  delay: 5 },
  { id: 'dp5', path: 'M720,350 C770,370 810,390 850,420',                r: 1.8, dur: 5,  delay: 7 },
] as const;

/** Frosted-glass metric cards */
const METRIC_BADGES = [
  {
    id: 'b1',
    label: 'NH-48 · Risk 0.91 · CRITICAL',
    dotColor: 'var(--lq-red)',
    pos: { top: '12%', left: '6%' } as const,
    delay: 0,
  },
  {
    id: 'b2',
    label: 'Agent rerouted SHP-1028',
    dotColor: 'var(--lq-cyan)',
    pos: { top: '18%', right: '5%' } as const,
    delay: 1,
  },
  {
    id: 'b3',
    label: 'SLA 94.2% ↑',
    dotColor: 'var(--lq-green)',
    pos: { bottom: '16%', left: '8%' } as const,
    delay: 0.5,
  },
  {
    id: 'b4',
    label: 'Fleet · 23 active units',
    dotColor: 'var(--lq-amber)',
    pos: { bottom: '12%', right: '7%' } as const,
    delay: 1.5,
  },
] as const;
