"use client";

import { motion } from "framer-motion";
import { Play, Loader2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AuraOrb } from "@/components/aura/AuraOrb";

interface Props {
  onRun: () => void;
  running: boolean;
  lastRunAt: string | null;
  runs: number;
}

export function Hero({ onRun, running, lastRunAt, runs }: Props) {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-30 pointer-events-none" />
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-10 sm:py-14">
        <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] gap-8 lg:gap-12 items-center">
          {/* ── Left: copy + CTA + stats ─────────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="max-w-2xl"
          >
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-primary/30 bg-primary/10 text-primary text-[11px] font-medium mb-4">
              <Zap className="h-3 w-3" />
              Multi-Agent · RL · MCP · Long-Term Memory
            </div>
            <h1 className="text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-tight leading-[1.1]">
              Why recommend? When? How confident?{" "}
              <span className="text-primary text-glow">How to improve?</span>
            </h1>
            <p className="mt-4 text-muted-foreground text-sm sm:text-base leading-relaxed">
              AURA shifts the system from a prediction engine to an{" "}
              <span className="text-foreground">autonomous decision-making platform</span>.
              Nine specialized agents reason over user context, retrieve long-term memory,
              ground on a knowledge graph, produce ranked candidates, learn from feedback
              via PPO, explain their choices, and verify safety — all coordinated by a
              single orchestrator.
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Button
                size="lg"
                onClick={onRun}
                disabled={running}
                className="bg-primary text-primary-foreground hover:bg-primary/90"
              >
                {running ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Play className="h-4 w-4 mr-2" />
                )}
                {running ? "Orchestrating…" : "Run Orchestration"}
              </Button>
              <div className="text-xs text-muted-foreground">
                {runs > 0 ? (
                  <>
                    <span className="font-mono text-foreground">{runs}</span> runs · last{" "}
                    <span className="font-mono">
                      {lastRunAt ? new Date(lastRunAt).toLocaleTimeString() : "—"}
                    </span>
                  </>
                ) : (
                  "No runs yet — click to start the full 9-agent loop"
                )}
              </div>
            </div>

            {/* stat strip */}
            <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: "Specialized Agents", value: "9", hint: "orchestrator + 8 specialists" },
                { label: "MCP Tool Servers",   value: "14", hint: "calendar · spotify · github…" },
                { label: "RL Algorithm",       value: "PPO", hint: "contextual bandits · DQN · CQL · IQL" },
                { label: "Retrieval",          value: "Hybrid", hint: "BM25 + dense (BGE-M3)" },
              ].map((s, i) => (
                <motion.div
                  key={s.label}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.1 + i * 0.06 }}
                >
                  <Card className="p-4 bg-card/60 backdrop-blur-sm">
                    <div className="text-2xl font-semibold tracking-tight">{s.value}</div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">{s.label}</div>
                    <div className="text-[10px] text-muted-foreground/70 mt-1 truncate">{s.hint}</div>
                  </Card>
                </motion.div>
              ))}
            </div>
          </motion.div>

          {/* ── Right: interactive AURA Orb ──────────────────────────────── */}
          <motion.div
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, delay: 0.2, type: "spring" }}
            className="relative"
          >
            <AuraOrb onRun={onRun} running={running} />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
