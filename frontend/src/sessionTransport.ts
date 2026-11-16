import { getStoredAuthToken, getWebSocketUrl, invalidateAuthentication } from "./api";

/** Coalesce pulse bursts and serialize refreshes. Dispose prevents queued stale work. */
export function createRefreshScheduler(refresh: () => Promise<void>, delayMs = 600) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = false;
  let pending = false;
  let disposed = false;
  const run = async () => {
    timer = undefined;
    if (disposed) return;
    if (running) { pending = true; return; }
    running = true;
    try { await refresh(); } finally {
      running = false;
      if (pending && !disposed) { pending = false; schedule(); }
    }
  };
  const schedule = () => {
    if (disposed) return;
    if (running) { pending = true; return; }
    if (!timer) timer = setTimeout(() => { void run(); }, delayMs);
  };
  return { schedule, dispose: () => { disposed = true; if (timer) clearTimeout(timer); } };
}

export function connectAuthenticatedEvents(
  onConnected: (connected: boolean) => void,
  onEvent: () => void,
  options: { createSocket?: (url: string) => WebSocket; retryDelayMs?: number; maxRetries?: number; authTimeoutMs?: number } = {}
): () => void {
  let stopped = false;
  let socket: WebSocket | undefined;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let authTimer: ReturnType<typeof setTimeout> | undefined;
  let attempts = 0;
  const token = getStoredAuthToken();
  const createSocket = options.createSocket ?? (url => new WebSocket(url));
  const retry = () => {
    onConnected(false);
    if (authTimer) clearTimeout(authTimer);
    if (stopped || getStoredAuthToken() !== token || attempts >= (options.maxRetries ?? 5)) return;
    const delay = Math.min((options.retryDelayMs ?? 1000) * 2 ** attempts++, 15000);
    reconnectTimer = setTimeout(connect, delay);
  };
  const connect = () => {
    if (stopped || !token || getStoredAuthToken() !== token) return;
    let authenticated = false;
    try { socket = createSocket(getWebSocketUrl()); } catch { retry(); return; }
    const current = socket;
    current.onopen = () => {
      if (stopped || getStoredAuthToken() !== token) { current.close(); return; }
      current.send(JSON.stringify({ type: "authenticate", token }));
      authTimer = setTimeout(() => current.close(), options.authTimeoutMs ?? 5000);
    };
    current.onmessage = event => {
      if (stopped || getStoredAuthToken() !== token) return;
      let data: { type?: string };
      try { data = JSON.parse(String(event.data)); } catch { return; }
      if (data.type === "authenticated") {
        authenticated = true;
        if (authTimer) clearTimeout(authTimer);
        onConnected(true);
      } else if (authenticated) onEvent();
    };
    current.onclose = event => {
      if (stopped) return;
      if (event.code === 4401 || event.code === 1008) {
        stopped = true;
        onConnected(false);
        if (getStoredAuthToken() === token) invalidateAuthentication();
        return;
      }
      retry();
    };
    current.onerror = () => { onConnected(false); current.close(); };
  };
  onConnected(false);
  connect();
  return () => {
    stopped = true;
    if (authTimer) clearTimeout(authTimer);
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
    onConnected(false);
  };
}
