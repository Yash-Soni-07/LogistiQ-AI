/**
 * useServerWarmup.ts
 *
 * Sends a single lightweight GET /health ping to the backend on mount so that
 * Google Cloud Run's cold-start completes before the user submits an auth form.
 *
 * - Uses native `fetch` (not apiClient) to avoid auth interceptors / tenant headers.
 * - Uses AbortController for safe cleanup on unmount.
 * - Accepts the full VITE_API_URL (e.g. ".../api/v1") and strips the suffix internally.
 * - On fetch error the status falls back to 'error' so the button re-enables and
 *   the user can still attempt sign-in (soft failure — never blocks indefinitely).
 */

import { useEffect, useState } from 'react';

export type WarmupStatus = 'waking' | 'connected' | 'error';

/** Strip the /api/v1 path so we can call the root health endpoint. */
function deriveBaseUrl(apiUrl: string): string {
  return apiUrl.trim().replace(/\/api\/v1\/?$/, '').replace(/\/$/, '');
}

export function useServerWarmup(apiUrl: string): { warmupStatus: WarmupStatus } {
  const [warmupStatus, setWarmupStatus] = useState<WarmupStatus>('waking');

  useEffect(() => {
    // In local development there is no cold-start — skip the ping immediately.
    if (!apiUrl || apiUrl.includes('localhost') || apiUrl.includes('127.0.0.1')) {
      setWarmupStatus('connected');
      return;
    }

    const controller = new AbortController();
    let mounted = true;

    const baseUrl = deriveBaseUrl(apiUrl);
    const healthUrl = `${baseUrl}/health`;

    const warmup = async (): Promise<void> => {
      try {
        const res = await fetch(healthUrl, {
          method: 'GET',
          signal: controller.signal,
          // No credentials / auth headers — this is a public liveness probe.
          cache: 'no-store',
        });

        if (!mounted) return;

        // Any HTTP response (even non-2xx) means the server is alive and
        // Cloud Run has fully initialised the container.
        if (res.status < 500) {
          setWarmupStatus('connected');
        } else {
          // 5xx → server errored but is at least responding.
          setWarmupStatus('error');
        }
      } catch (err) {
        if (!mounted) return;
        if ((err as Error).name === 'AbortError') return; // intentional cleanup

        // Network-level failure (CORS preflight on health is fine — fetch throws
        // for actual network errors, not CORS).  Soft-fail so the user can retry.
        setWarmupStatus('error');
      }
    };

    void warmup();

    return () => {
      mounted = false;
      controller.abort();
    };
  // apiUrl is derived from import.meta.env — it never changes at runtime,
  // but we keep it in deps for correctness in tests / Storybook.
  }, [apiUrl]);

  return { warmupStatus };
}
