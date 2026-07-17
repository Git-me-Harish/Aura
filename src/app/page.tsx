"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { Header } from "@/components/aura/Header";
import { Hero } from "@/components/aura/Hero";
import { AgentNetwork } from "@/components/aura/AgentNetwork";
import { ContextPanel } from "@/components/aura/ContextPanel";
import { RecommendationsPanel } from "@/components/aura/RecommendationsPanel";
import { RLMetricsPanel } from "@/components/aura/RLMetricsPanel";
import { MCPToolsPanel } from "@/components/aura/MCPToolsPanel";
import { MemoryPanel } from "@/components/aura/MemoryPanel";
import { SafetyPanel } from "@/components/aura/SafetyPanel";
import { OrchestrationTrace } from "@/components/aura/OrchestrationTrace";
import { MetricsStrip } from "@/components/aura/MetricsStrip";
import { Footer } from "@/components/aura/Footer";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { auraApi, auraSocket } from "@/lib/aura/api";
import { useStreamingOrchestration } from "@/hooks/use-streaming-orchestration";
import type {
  AgentStatus, AgentName, ContextSnapshot, MemoryRecord,
  RecommendationItem, Explanation, SafetyVerdict, AgentTrace,
  RLMetrics, MCPTool, DashboardMetrics, OrchestrationResult,
} from "@/lib/aura/types";

const TOTAL_AGENTS = 9;

export default function Page() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [orchResult, setOrchResult] = useState<OrchestrationResult | null>(null);
  const [runs, setRuns] = useState(0);
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);

  const [ctx, setCtx] = useState<ContextSnapshot | null>(null);
  const [memory, setMemory] = useState<MemoryRecord[]>([]);
  const [mcpTools, setMcpTools] = useState<MCPTool[]>([]);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);

  const [rlMetrics, setRlMetrics] = useState<RLMetrics | null>(null);
  const [rewardHistory, setRewardHistory] = useState<{ ts: number; reward: number }[]>([]);
  const [policyVersions, setPolicyVersions] = useState<any[]>([]);

  const [pendingItemId, setPendingItemId] = useState<string | null>(null);
  const [pendingTool, setPendingTool] = useState<string | null>(null);
  const [mcpResults, setMcpResults] = useState<Record<string, any>>({});
  const [training, setTraining] = useState(false);

  // New: LLM provider + RL backend labels for the header
  const [llmProvider, setLlmProvider] = useState<string>("");
  const [rlBackend, setRlBackend] = useState<string>("");

  // Streaming orchestration hook
  const {
    running, liveSteps, result: streamResult, runOrchestration,
  } = useStreamingOrchestration();

  // ── Initial load ──────────────────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const [ag, mem, tools, met, last, hist, info] = await Promise.all([
          auraApi.agentsStatus(),
          auraApi.memory(),
          auraApi.mcpTools(),
          auraApi.metrics(),
          auraApi.lastOrchestration(),
          auraApi.rlHistory(50),
          auraApi.info(),
        ]);
        setAgents(ag);
        setMemory(mem.records);
        setMcpTools(tools);
        setMetrics(met);
        setLlmProvider(info.llm_provider || "");
        setRlBackend(info.rl_backend || "");
        if (last.result) {
          setOrchResult(last.result);
          setRuns(last.runs);
          setLastRunAt(last.result.finished_at);
          setCtx(last.result.trace.find((t: AgentTrace) => t.agent === "context")?.artifacts?.context ?? null);
          const memArt = last.result.trace.find((t: AgentTrace) => t.agent === "memory")?.artifacts?.memories;
          if (Array.isArray(memArt) && memArt.length > 0) setMemory(memArt);
        }
        if (hist.actions?.length) {
          setRewardHistory(hist.actions.map((a: any, i: number) => ({ ts: i, reward: a.reward ?? 0 })));
        }
        if (hist.policy_updates?.length) {
          setPolicyVersions(hist.policy_updates);
        }
        const rlm = await auraApi.rlMetrics();
        setRlMetrics(rlm);
      } catch (e: any) {
        toast.error("Failed to load AURA state", { description: e.message });
      }
    })();

    // WebSocket for live RL ticks + streaming orchestration events
    const ws = auraSocket((msg) => {
      if (msg.type === "tick") {
        setRlMetrics(msg.rl);
        if (msg.agents?.length) setAgents(msg.agents);
      } else if (msg.type === "rl_update") {
        setRlMetrics(msg.rl);
      }
    });
    return () => ws.close();
  }, []);

  // ── When streaming orchestration completes, hydrate the UI ────────────
  useEffect(() => {
    if (streamResult) {
      setOrchResult(streamResult);
      setRuns((r) => r + 1);
      setLastRunAt(streamResult.finished_at);
      const ctxArt = streamResult.trace.find((t) => t.agent === "context")?.artifacts?.context;
      if (ctxArt) setCtx(ctxArt);
      const memArt = streamResult.trace.find((t) => t.agent === "memory")?.artifacts?.memories;
      if (Array.isArray(memArt) && memArt.length > 0) setMemory(memArt);
      // Refresh agent status + metrics
      Promise.all([auraApi.agentsStatus(), auraApi.metrics(), auraApi.rlMetrics()])
        .then(([ag, met, rlm]) => {
          setAgents(ag);
          setMetrics(met);
          setRlMetrics(rlm);
        })
        .catch(() => {});
      toast.success("Orchestration complete", {
        description: `${streamResult.recommendations.length} recommendations · policy ${streamResult.policy_version}`,
      });
    }
  }, [streamResult]);

  // ── User action → RL pipeline ─────────────────────────────────────────
  const onUserAction = useCallback(async (itemId: string, action: "click" | "like" | "purchase" | "skip") => {
    setPendingItemId(itemId);
    try {
      const r = await auraApi.rlAction(itemId, action);
      setRewardHistory((h) => [...h, { ts: Date.now(), reward: r.reward }]);
      const rlm = await auraApi.rlMetrics();
      setRlMetrics(rlm);
      const hist = await auraApi.rlHistory(60);
      if (hist.policy_updates?.length) setPolicyVersions(hist.policy_updates);
      toast.success(`Action streamed → RL pipeline`, {
        description: `${action} on ${itemId} · reward ${r.reward.toFixed(3)} · policy ${r.policy_version}`,
      });
    } catch (e: any) {
      toast.error("Failed to stream action", { description: e.message });
    } finally {
      setPendingItemId(null);
    }
  }, []);

  // ── Manual policy train ───────────────────────────────────────────────
  const onTrain = useCallback(async () => {
    setTraining(true);
    try {
      const snap = await auraApi.rlTrain();
      setPolicyVersions((p) => [...p, snap]);
      const rlm = await auraApi.rlMetrics();
      setRlMetrics(rlm);
      toast.success("Policy updated", {
        description: `${snap.version} · mean_reward ${snap.mean_reward.toFixed(3)}`,
      });
    } catch (e: any) {
      toast.error("Training failed", { description: e.message });
    } finally {
      setTraining(false);
    }
  }, []);

  // ── MCP tool invoke ───────────────────────────────────────────────────
  const onInvokeTool = useCallback(async (tool: string, method: string) => {
    setPendingTool(tool);
    try {
      const r = await auraApi.mcpCall(tool, method, {});
      if (r.error) {
        toast.error(`MCP ${tool}.${method} failed`, { description: r.error });
      } else {
        setMcpResults((m) => ({ ...m, [tool]: r.result }));
        toast.success(`MCP ${tool}.${method}`, {
          description: `${r.duration_ms}ms`,
        });
      }
    } catch (e: any) {
      toast.error("MCP call failed", { description: e.message });
    } finally {
      setPendingTool(null);
    }
  }, []);

  // ── Periodic metric refresh ───────────────────────────────────────────
  useEffect(() => {
    const id = setInterval(() => {
      auraApi.metrics().then(setMetrics).catch(() => {});
      auraApi.rlMetrics().then(setRlMetrics).catch(() => {});
    }, 8000);
    return () => clearInterval(id);
  }, []);

  const agentsReady = agents.filter(a => a.status === "ready").length;
  const recs: RecommendationItem[] = orchResult?.recommendations ?? [];
  const explanations: Explanation[] = orchResult?.explanations ?? [];
  const safety: SafetyVerdict[] = orchResult?.safety_verdicts ?? [];
  const trace: AgentTrace[] = orchResult?.trace ?? [];

  // Merge live steps into trace for display while running
  const displayTrace: AgentTrace[] = running && liveSteps.length > 0
    ? liveSteps.map((s, i) => ({
        agent: s.agent,
        started_at: s.startedAt,
        finished_at: s.startedAt,
        duration_ms: s.duration_ms ?? 0,
        input_summary: "",
        output_summary: s.status === "thinking" ? "running…" : (s.output_summary || ""),
        artifacts: (s.artifacts as any) || {},
      }))
    : trace;

  return (
    <div className="min-h-screen flex flex-col">
      <Header
        policyVersion={rlMetrics?.policy_version ?? null}
        samplesSeen={rlMetrics?.samples_seen ?? 0}
        agentsReady={agentsReady}
        totalAgents={TOTAL_AGENTS}
        rlBackend={rlBackend}
        llmProvider={llmProvider}
      />

      <main className="flex-1">
        <Hero
          onRun={runOrchestration}
          running={running}
          lastRunAt={lastRunAt}
          runs={runs}
        />

        {/* Live streaming banner while orchestrating */}
        {running && liveSteps.length > 0 && (
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 -mt-2 mb-2">
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-primary/30 bg-primary/5 p-3 flex items-center gap-3"
            >
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              <span className="text-xs font-medium">Streaming orchestration</span>
              <div className="flex items-center gap-1 ml-2 flex-wrap">
                {liveSteps.map((s, i) => (
                  <Badge
                    key={`${s.agent}-${i}`}
                    variant="outline"
                    className={`text-[9px] py-0 px-1.5 ${
                      s.status === "thinking"
                        ? "border-amber-500/40 text-amber-500"
                        : "border-green-500/40 text-green-500"
                    }`}
                  >
                    {s.agent}
                  </Badge>
                ))}
              </div>
            </motion.div>
          </div>
        )}

        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 pb-10 space-y-6">
          {/* Metrics strip */}
          <MetricsStrip metrics={metrics} />

          {/* Agent network + Context */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2 p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h3 className="text-sm font-semibold">Multi-Agent Orchestration Network</h3>
                  <p className="text-[11px] text-muted-foreground">
                    Live status — emerald=ready, amber=thinking, dashed=control
                  </p>
                </div>
              </div>
              <AgentNetwork
                agents={agents}
                liveSteps={running ? liveSteps : undefined}
                activeAgent={null}
                onSelect={() => {}}
              />
            </Card>

            <ContextPanel ctx={ctx} />
          </div>

          {/* Recommendations + RL metrics */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RecommendationsPanel
              items={recs}
              explanations={explanations}
              safety={safety}
              loading={running}
              onAction={onUserAction}
              pendingItemId={pendingItemId}
            />
            <RLMetricsPanel
              metrics={rlMetrics}
              rewardHistory={rewardHistory}
              policyVersions={policyVersions}
              onTrain={onTrain}
              training={training}
            />
          </div>

          {/* Trace + Safety */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <OrchestrationTrace trace={displayTrace} />
            </div>
            <SafetyPanel verdicts={safety} />
          </div>

          {/* MCP + Memory */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <MCPToolsPanel
              tools={mcpTools}
              onInvoke={onInvokeTool}
              pendingTool={pendingTool}
              lastResult={mcpResults}
            />
            <MemoryPanel records={memory} />
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}
