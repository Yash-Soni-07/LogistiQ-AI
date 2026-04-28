import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/stores/auth.store';

interface UseWebSocketOptions {
  reconnect?: boolean;
  maxReconnectAttempts?: number;
  initialReconnectDelayMs?: number;
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) {
      return null;
    }
    const payload = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, '=');
    const decoded = atob(padded);
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function isJwtExpired(token: string): boolean {
  const payload = decodeJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== 'number') {
    return false;
  }
  const nowSeconds = Math.floor(Date.now() / 1000);
  return nowSeconds >= exp;
}

function normalizeWsPath(path: string): string {
  const trimmed = path.trim();
  const withLeadingSlash = trimmed.startsWith('/') ? trimmed : `/${trimmed}`;
  const withWsPrefix = withLeadingSlash.startsWith('/ws') ? withLeadingSlash : `/ws${withLeadingSlash}`;
  return withWsPrefix.replace(/\/{2,}/g, '/');
}

function buildWebSocketUrl(path: string, token: string): string {
  const rawBase = (import.meta.env.VITE_WS_URL as string | undefined)?.trim() || 'ws://localhost:8000';
  let parsedBase: URL;
  try {
    parsedBase = new URL(rawBase);
  } catch {
    parsedBase = new URL(`ws://${rawBase}`);
  }

  const protocol =
    parsedBase.protocol === 'https:'
      ? 'wss:'
      : parsedBase.protocol === 'http:'
        ? 'ws:'
        : parsedBase.protocol;

  const normalizedPath = normalizeWsPath(path);
  return `${protocol}//${parsedBase.host}${normalizedPath}?token=${encodeURIComponent(token)}`;
}

export function useWebSocket(path: string, onMessage: (data: any) => void, options?: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const intentionalCloseRef = useRef(false);

  const reconnect = options?.reconnect ?? true;
  const maxReconnectAttempts = options?.maxReconnectAttempts ?? 8;
  const initialReconnectDelayMs = options?.initialReconnectDelayMs ?? 400;

  // Store onMessage in a ref so we never add it to the effect deps.
  // This prevents the socket from reconnecting every render when an
  // inline arrow function is passed as the callback.
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    const token = useAuthStore.getState().token;
    if (!token) return;
    if (isJwtExpired(token)) {
      useAuthStore.getState().logout();
      return;
    }

    let disposed = false;
    const fullUrl = buildWebSocketUrl(path, token);

    const clearHeartbeat = () => {
      if (heartbeatTimerRef.current !== null) {
        window.clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
    };

    const clearReconnect = () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      if (!reconnect || disposed || intentionalCloseRef.current) {
        return;
      }
      if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
        return;
      }
      const delay = Math.min(initialReconnectDelayMs * (2 ** reconnectAttemptsRef.current), 8000);
      reconnectAttemptsRef.current += 1;
      reconnectTimerRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    };

    const connect = () => {
      if (disposed) {
        return;
      }

      intentionalCloseRef.current = false;
      const socket = new WebSocket(fullUrl);
      wsRef.current = socket;

      socket.onopen = () => {
        if (disposed) {
          return;
        }
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;

        clearHeartbeat();
        heartbeatTimerRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send('ping');
          }
        }, 25000);
      };

      socket.onclose = (event) => {
        setIsConnected(false);
        clearHeartbeat();
        if (event.code === 1008) {
          // Server policy violation (commonly invalid/expired auth token).
          intentionalCloseRef.current = true;
          useAuthStore.getState().logout();
          return;
        }
        scheduleReconnect();
      };

      socket.onerror = (err) => {
        // Avoid noisy logs during intentional cleanup or strict-mode remount cycles.
        if (disposed || intentionalCloseRef.current) {
          return;
        }
        if (import.meta.env.DEV) {
          console.warn('[useWebSocket] connection error on', path, err);
        }
      };

      socket.onmessage = (e) => {
        try {
          onMessageRef.current(JSON.parse(e.data));
        } catch {
          onMessageRef.current(e.data);
        }
      };
    };

    // Delay socket creation by one tick so React StrictMode's mount/unmount
    // verification cycle does not create redundant transient connections.
    const bootstrapTimer = window.setTimeout(connect, 0);

    return () => {
      disposed = true;
      intentionalCloseRef.current = true;
      setIsConnected(false);
      window.clearTimeout(bootstrapTimer);
      clearHeartbeat();
      clearReconnect();
      if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
        wsRef.current.close();
      }
      wsRef.current = null;
    };
  // path is the only dependency — onMessage changes are handled by the ref above
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, reconnect, maxReconnectAttempts, initialReconnectDelayMs]);

  return { isConnected, ws: wsRef.current };
}
