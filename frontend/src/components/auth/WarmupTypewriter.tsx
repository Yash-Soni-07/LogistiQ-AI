/**
 * WarmupTypewriter.tsx
 *
 * A premium AI-insight panel that cycles through product-pitch phrases with a
 * typewriter animation.  Rendered persistently on the auth pages — independent
 * of backend warmup state.
 *
 * Architecture:
 *  - All animation state lives in refs → zero unnecessary re-renders per tick.
 *  - Only `displayText` (one string) is React state.
 *  - Scoped <style> tag for cursor + dot keyframes — no global CSS pollution.
 *  - AbortController-equivalent via mountedRef for safe unmount cleanup.
 */

import { useEffect, useRef, useState } from 'react';

// ─── Phrases — crisp, punchy, ≤ 58 chars each ────────────────────────────────
const PHRASES: readonly string[] = [
  'AI that reroutes freight before the storm hits.',
  'From port delays to certainty — in milliseconds.',
  'Disruptions predicted. Shipments protected.',
  'Logistics decisions that took hours now take seconds.',
  'See every shipment risk before it becomes a crisis.',
  'Not just tracking — thinking. AI that acts for you.',
  '150+ carriers. One intelligent command center.',
  'The freight OS your competitors don\'t know exists.',
  'Turn supply chain chaos into operational clarity.',
  'When disruptions strike, LogistiQ has already rerouted.',
] as const;

// ─── Timing ───────────────────────────────────────────────────────────────────
const TYPING_MS  = 26;   // ms per character typed  (fast = feels snappy & confident)
const ERASE_MS   = 14;   // ms per character erased (faster erase = snappier cycling)
const HOLD_MS    = 1500; // pause after fully typed
const PAUSE_MS   = 200;  // pause before next phrase begins

// ─── Scoped CSS ───────────────────────────────────────────────────────────────
const SCOPED_STYLES = `
  @keyframes lq-tw-blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
  }
  @keyframes lq-tw-dot-pulse {
    0%, 100% { opacity: 1;   transform: scale(1);   }
    50%       { opacity: 0.4; transform: scale(0.75); }
  }
  .lq-tw-cursor {
    display: inline-block;
    margin-left: 1px;
    color: var(--lq-cyan);
    font-weight: 200;
    line-height: 1;
    animation: lq-tw-blink 1s step-end infinite;
    user-select: none;
  }
  .lq-tw-live-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--lq-cyan);
    flex-shrink: 0;
    animation: lq-tw-dot-pulse 2.2s ease-in-out infinite;
  }
`;

export function WarmupTypewriter() {
  const [displayText, setDisplayText] = useState('');

  // All mutable animation state → refs only (no spurious renders)
  const animRef  = useRef({ phraseIndex: 0, charIndex: 0, isErasing: false });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted  = useRef(true);

  useEffect(() => {
    mounted.current = true;

    const tick = (): void => {
      if (!mounted.current) return;

      const a      = animRef.current;
      const phrase = PHRASES[a.phraseIndex];

      if (!a.isErasing) {
        // ── Typing ────────────────────────────────────────────────────────────
        if (a.charIndex < phrase.length) {
          a.charIndex += 1;
          setDisplayText(phrase.slice(0, a.charIndex));
          timerRef.current = setTimeout(tick, TYPING_MS);
        } else {
          // Hold at end, then start erasing
          timerRef.current = setTimeout(() => {
            if (!mounted.current) return;
            a.isErasing = true;
            tick();
          }, HOLD_MS);
        }
      } else {
        // ── Erasing ───────────────────────────────────────────────────────────
        if (a.charIndex > 0) {
          a.charIndex -= 1;
          setDisplayText(phrase.slice(0, a.charIndex));
          timerRef.current = setTimeout(tick, ERASE_MS);
        } else {
          // Done erasing → next phrase
          a.phraseIndex = (a.phraseIndex + 1) % PHRASES.length;
          a.isErasing   = false;
          timerRef.current = setTimeout(tick, PAUSE_MS);
        }
      }
    };

    timerRef.current = setTimeout(tick, PAUSE_MS);

    return () => {
      mounted.current = false;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []); // empty deps — animation is fully ref-driven

  return (
    <>
      <style>{SCOPED_STYLES}</style>

      {/*
        ┌──────────────────────────────────────────────────────┐
        │  ◈ LOGISTIQ AI                  Intelligent Freight OS│
        │  ──────────────────────────────────────────────────  │
        │  AI that reroutes freight before the storm hits.|    │
        └──────────────────────────────────────────────────────┘
        Visual: subtle left-accent bar + top shimmer line.
        No solid background — card feel without the "box" look.
      */}
      <div
        aria-live="polite"
        aria-label="LogistiQ AI product insight"
        style={{
          width: '100%',
          marginBottom: '16px',
          position: 'relative',
          borderRadius: '10px',
          border: '1px solid rgba(34, 211, 238, 0.18)',
          overflow: 'hidden',
          // Left accent stripe
          borderLeft: '3px solid var(--lq-cyan)',
        }}
      >
        {/* Top shimmer gradient line */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '1px',
            background:
              'linear-gradient(90deg, transparent 0%, var(--lq-cyan) 40%, transparent 100%)',
            opacity: 0.35,
          }}
        />

        {/* Card body */}
        <div style={{ padding: '10px 14px 11px 14px' }}>

          {/* ── Header row ───────────────────────────────────────────────────── */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '9px',
            }}
          >
            {/* Brand badge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
              <span className="lq-tw-live-dot" />
              <span
                style={{
                  fontFamily: 'var(--lq-font-mono)',
                  fontSize: '10px',
                  fontWeight: 700,
                  letterSpacing: '0.09em',
                  color: 'var(--lq-cyan)',
                  textTransform: 'uppercase',
                }}
              >
                LogistiQ AI
              </span>
            </div>

            {/* Right label */}
            <span
              style={{
                fontFamily: 'var(--lq-font-mono)',
                fontSize: '9px',
                fontWeight: 500,
                letterSpacing: '0.08em',
                color: 'var(--lq-text-dim)',
                textTransform: 'uppercase',
              }}
            >
              Intelligent Freight OS
            </span>
          </div>

          {/* ── Thin divider ────────────────────────────────────────────────── */}
          <div
            aria-hidden="true"
            style={{
              height: '1px',
              background: 'var(--lq-border)',
              marginBottom: '11px',
            }}
          />

          {/* ── Typewriter phrase ────────────────────────────────────────────── */}
          <p
            style={{
              margin: 0,
              fontFamily: 'var(--lq-font-ui)',
              fontSize: '13.5px',
              fontWeight: 500,
              lineHeight: 1.5,
              color: 'var(--lq-text-bright)',
              letterSpacing: '-0.1px',
              minHeight: '20px',     // prevents layout shift when text is empty
            }}
          >
            {displayText}
            <span className="lq-tw-cursor" aria-hidden="true">|</span>
          </p>
        </div>
      </div>
    </>
  );
}
