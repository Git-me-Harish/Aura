"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AgentTrace } from "@/lib/aura/types";

interface Props {
  trace: AgentTrace[];
}

const AGENT_LABEL: Record<string, string> = {
  orchestrator: "Orchestrator",
  preference: "Preference",
  context: "Context",
  memory: "Memory",
  knowledge: "Knowledge",
  recommendation: "Recommendation",
  rl: "RL Learning",
  explanation: "Explanation",
  safety: "Safety",
};

export function OrchestrationTrace({ trace }: Props) {
  const totalMs = trace.reduce((s, t) => s + t.duration_ms, 0);
  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Orchestration Trace</h3>
          <p className="text-[11px] text-muted-foreground">
            Per-agent execution timeline · {trace.length} steps
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[11px] text-primary">
          {totalMs}ms total
        </Badge>
      </div>

      {trace.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">
          No trace yet. Run orchestration to see the per-agent timeline.
        </div>
      ) : (
        <div className="space-y-2">
          {trace.map((t, i) => {
            const maxMs = Math.max(...trace.map(x => x.duration_ms || 1), 1);
            const widthPct = Math.max(4, ((t.duration_ms || 0) / maxMs) * 100);
            return (
              <motion.div
                key={`${t.agent}-${i}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: i * 0.05 }}
                className="rounded-lg border border-border bg-background/40 p-2.5"
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-muted-foreground">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-[12px] font-medium">
                      {AGENT_LABEL[t.agent] ?? t.agent}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-primary">
                    {t.duration_ms}ms
                  </span>
                </div>
                <div className="h-1.5 bg-muted/40 rounded-full overflow-hidden mb-1.5">
                  <motion.div
                    className="h-full bg-primary/70"
                    initial={{ width: 0 }}
                    animate={{ width: `${widthPct}%` }}
                    transition={{ duration: 0.4, delay: i * 0.05 }}
                  />
                </div>
                <div className="text-[10px] text-muted-foreground font-mono truncate">
                  → {t.output_summary}
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
