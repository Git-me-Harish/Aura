/**
 * AURA API client.
 *
 * All requests go through the Next.js dev server (port 3000), which the
 * Caddy gateway forwards to the Python FastAPI backend on port 8000 via
 * the XTransformPort query parameter.
 *
 * Auth: every request includes the NextAuth session JWT as
 *       `Authorization: Bearer <jwt>` so FastAPI can identify the user.
 */

import { useSession } from "next-auth/react";

const BACKEND_PORT = 8000;

function apiUrl(path: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}XTransformPort=${BACKEND_PORT}`;
}

/**
 * Fetch the current NextAuth session JWT (client-side).
 * Returns null if not signed in — FastAPI will then fall back to DEMO_USER.
 */
async function getJwt(): Promise<string | null> {
  try {
    const r = await fetch("/api/auth/session");
    if (!r.ok) return null;
    const session = await r.json();
    // NextAuth's default JWT is encrypted; the session endpoint decrypts it.
    // For the FastAPI bridge we use a custom callbacks.jwt() that returns a
    // SIGNED (not encrypted) token — exposed as `accessToken` on the session.
    return session?.accessToken || null;
  } catch {
    return null;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getJwt();
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`AURA API ${path} → ${res.status}: ${text}`);
  }
  return (await res.json()) as T;
}

export const auraApi = {
  health: () => apiFetch<{ status: string; service: string; ts: string }>("/api/health"),

  info: () =>
    apiFetch<{
      name: string;
      full_name: string;
      vision: string;
      version: string;
      llm_provider: string;
      rl_backend: string;
      agents: { name: string; role: string }[];
      tech_stack: Record<string, string[]>;
    }>("/api/info"),

  orchestrate: () =>
    apiFetch<{ status: string; user_id: string; policy_version: string; ts: string }>(
      "/api/orchestrate",
      { method: "POST" }
    ),

  lastOrchestration: () =>
    apiFetch<{ result: any | null; runs: number }>("/api/orchestrate/last"),

  agentsStatus: () => apiFetch<any[]>("/api/agents/status"),

  preference: () => apiFetch<any>("/api/preference"),
  context: () => apiFetch<any>("/api/context"),
  memory: () => apiFetch<{ records: any[] }>("/api/memory"),
  knowledge: (q: string) => apiFetch<any>(`/api/knowledge?q=${encodeURIComponent(q)}`),

  mcpTools: () => apiFetch<any[]>("/api/mcp/tools"),
  mcpCall: (tool: string, method: string, args: Record<string, any> = {}) =>
    apiFetch<any>("/api/mcp/call", {
      method: "POST",
      body: JSON.stringify({ tool, method, args }),
    }),

  // ── OAuth ────────────────────────────────────────────────────────────
  oauthStatus: () =>
    apiFetch<{ providers: Record<string, { configured: boolean; connected: boolean }> }>(
      "/api/oauth/status"
    ),
  oauthLogin: (provider: string) =>
    apiFetch<{ auth_url: string; state: string }>(`/api/oauth/${provider}/login`),
  oauthDisconnect: (provider: string) =>
    apiFetch<{ status: string }>(`/api/oauth/${provider}`, { method: "DELETE" }),

  // ── RL ───────────────────────────────────────────────────────────────
  rlMetrics: () => apiFetch<any>("/api/rl/metrics"),
  rlTrain: () => apiFetch<any>("/api/rl/train", { method: "POST" }),
  rlAction: (item_id: string, action: string) =>
    apiFetch<any>("/api/rl/action", {
      method: "POST",
      body: JSON.stringify({ item_id, action }),
    }),
  rlHistory: (limit = 100) => apiFetch<any>(`/api/rl/history?limit=${limit}`),

  metrics: () => apiFetch<any>("/api/metrics"),
  dataSummary: () => apiFetch<any>("/api/data/summary"),
};

/**
 * Open a WebSocket to the AURA backend. Uses the same XTransformPort
 * convention as REST — the Caddy gateway will route to port 8000.
 *
 * NOTE: WebSocket doesn't easily support custom headers in browsers, so the
 * FastAPI `/api/ws` endpoint accepts unauthenticated connections (the demo
 * user is used). In production, pass the JWT as a query string param.
 */
export function auraSocket(onMessage: (msg: any) => void): WebSocket {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const directBackendHost = `${window.location.hostname}:${BACKEND_PORT}`;
  const wsHost =
    window.location.port === "3000" && (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
      ? directBackendHost
      : window.location.host;
  const ws = new WebSocket(`${proto}//${wsHost}/api/ws?XTransformPort=${BACKEND_PORT}`);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onerror = () => {
    /* silent — WebSocket is best-effort for live ticks */
  };
  return ws;
}
