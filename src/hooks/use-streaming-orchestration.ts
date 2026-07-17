/**
 * AURA — streaming orchestration hook.
 *
 * Replaces the old "fire orchestrate, wait for full result" flow with a
 * streaming model:
 *
 *   1. POST /api/orchestrate           — kicks off the run, returns immediately
 *   2. WebSocket receives `agent_start` → animate the agent node "thinking"
 *   3. WebSocket receives `agent_step`  → mark the agent "ready", show output
 *   4. WebSocket receives `orchestration_complete` → final result is in
 *
 * The hook exposes:
 *   - `running`             — true while a run is in flight
 *   - `liveSteps`           — array of {agent, status, duration_ms, output_summary}
 *                             appended in real time as agents complete
 *   - `result`              — the final OrchestrationResult (null until complete)
 *   - `runOrchestration()`  — kick off a new run
 *   - `error`               — last error, if any
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { auraApi, auraSocket } from "@/lib/aura/api";
import type { AgentName, AgentTrace, OrchestrationResult } from "@/lib/aura/types";

export interface LiveAgentStep {
  agent: AgentName;
  status: "thinking" | "ready";
  startedAt: string;
  duration_ms?: number;
  output_summary?: string;
  artifacts?: Record<string, unknown>;
}

export interface StreamingOrchestrationState {
  running: boolean;
  liveSteps: LiveAgentStep[];
  result: OrchestrationResult | null;
  error: string | null;
  runOrchestration: () => Promise<void>;
  reset: () => void;
}

export function useStreamingOrchestration(): StreamingOrchestrationState {
  const [running, setRunning] = useState(false);
  const [liveSteps, setLiveSteps] = useState<LiveAgentStep[]>([]);
  const [result, setResult] = useState<OrchestrationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // ── WebSocket listener ─────────────────────────────────────────────────
  useEffect(() => {
    const ws = auraSocket((msg) => {
      if (msg.type === "agent_start" && msg.request_id === requestId) {
        setLiveSteps((prev) => [
          ...prev,
          {
            agent: msg.agent,
            status: "thinking",
            startedAt: msg.ts,
          },
        ]);
      } else if (msg.type === "agent_step" && msg.request_id === requestId) {
        setLiveSteps((prev) =>
          prev.map((s, i) => {
            // Update the LAST matching agent step (in case of duplicates)
            const lastMatchIdx = prev
              .map((p, idx) => (p.agent === msg.agent ? idx : -1))
              .filter((idx) => idx >= 0)
              .pop();
            if (i === lastMatchIdx) {
              return {
                ...s,
                status: "ready" as const,
                duration_ms: msg.duration_ms,
                output_summary: msg.output_summary,
                artifacts: msg.artifacts,
              };
            }
            return s;
          })
        );
      } else if (msg.type === "orchestration_complete" && msg.request_id === requestId) {
        setResult(msg.result as OrchestrationResult);
        setRunning(false);
      }
    });
    wsRef.current = ws;
    return () => ws.close();
  }, [requestId]);

  // ── Kick off a run ─────────────────────────────────────────────────────
  const runOrchestration = useCallback(async () => {
    setRunning(true);
    setError(null);
    setLiveSteps([]);
    setResult(null);
    try {
      const r = await auraApi.orchestrate();
      // The backend returns {status: "started", ...} immediately. The actual
      // per-agent progress streams over the WebSocket. We accept any
      // orchestration event while running (the request_id matching is a
      // bonus filter — if the backend didn't echo it, we just listen to all).
      if ((r as any).request_id) setRequestId((r as any).request_id);
      else setRequestId("__live__");  // sentinel — accept all events
    } catch (e: any) {
      setError(e.message);
      setRunning(false);
    }
  }, []);

  const reset = useCallback(() => {
    setRunning(false);
    setLiveSteps([]);
    setResult(null);
    setError(null);
    setRequestId(null);
  }, []);

  return { running, liveSteps, result, error, runOrchestration, reset };
}
