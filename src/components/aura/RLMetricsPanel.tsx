"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Brain, TrendingUp, RefreshCw, Loader2 } from "lucide-react";
import type { RLMetrics } from "@/lib/aura/types";

interface Props {
  metrics: RLMetrics | null;
  rewardHistory: { ts: number; reward: number }[];
  policyVersions: { version: string; mean_reward: number; samples: number; updated_at: string }[];
  onTrain: () => void;
  training: boolean;
}

export function RLMetricsPanel({ metrics, rewardHistory, policyVersions, onTrain, training }: Props) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 2500);
    return () => clearInterval(id);
  }, []);

  const cumulativeData = rewardHistory.reduce<{ x: number; y: number }[]>((acc, p, i) => {
    const prev = i > 0 ? acc[i - 1].y : 0;
    acc.push({ x: i, y: prev + p.reward });
    return acc;
  }, []);

  const recent = rewardHistory.slice(-40).map((p, i) => ({ x: i, reward: p.reward }));
  const policyData = policyVersions.slice(-12).map((p, i) => ({
    x: i,
    mean_reward: p.mean_reward,
    version: p.version,
  }));

  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          <div>
            <h3 className="text-sm font-semibold">Reinforcement Learning</h3>
            <p className="text-[11px] text-muted-foreground">
              PPO policy · state→context · action→recommendation · reward→feedback
            </p>
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={onTrain} disabled={training} className="h-7 text-[11px]">
          {training ? (
            <Loader2 className="h-3 w-3 mr-1 animate-spin" />
          ) : (
            <RefreshCw className="h-3 w-3 mr-1" />
          )}
          Train step
        </Button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <MetricTile
          label="Cumulative Reward"
          value={metrics?.cumulative_reward?.toFixed(2) ?? "—"}
          accent="primary"
        />
        <MetricTile
          label="Reward Growth"
          value={metrics ? (metrics.reward_growth >= 0 ? "+" : "") + metrics.reward_growth.toFixed(3) : "—"}
          accent={metrics && metrics.reward_growth >= 0 ? "primary" : "destructive"}
        />
        <MetricTile
          label="Policy Regret"
          value={metrics?.policy_regret?.toFixed(3) ?? "—"}
          accent="muted"
        />
        <MetricTile
          label="Samples Seen"
          value={metrics?.samples_seen?.toString() ?? "—"}
          accent="accent"
        />
      </div>

      <div className="space-y-3">
        <ChartBlock title="Cumulative reward (live)">
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={cumulativeData} key={`cum-${tick}`}>
              <defs>
                <linearGradient id="cumGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" strokeOpacity={0.7} />
              <XAxis dataKey="x" hide />
              <YAxis tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} stroke="var(--border)" width={36} />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  color: "var(--popover-foreground)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                labelStyle={{ color: "var(--popover-foreground)" }}
                itemStyle={{ color: "var(--popover-foreground)" }}
              />
              <Area
                type="monotone"
                dataKey="y"
                stroke="var(--chart-1)"
                strokeWidth={2}
                fill="url(#cumGrad)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartBlock>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <ChartBlock title="Recent rewards (rolling 40)">
            <ResponsiveContainer width="100%" height={100}>
              <LineChart data={recent}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" strokeOpacity={0.7} />
                <XAxis dataKey="x" hide />
                <YAxis domain={[-0.5, 1.1]} tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} stroke="var(--border)" width={32} />
                <Tooltip
                  contentStyle={{
                    background: "var(--popover)",
                    color: "var(--popover-foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "var(--popover-foreground)" }}
                  itemStyle={{ color: "var(--popover-foreground)" }}
                />
                <Line
                  type="monotone"
                  dataKey="reward"
                  stroke="var(--chart-2)"
                  strokeWidth={1.8}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </ChartBlock>

          <ChartBlock title="Mean reward per policy version">
            <ResponsiveContainer width="100%" height={100}>
              <BarChart data={policyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" strokeOpacity={0.7} />
                <XAxis dataKey="x" hide />
                <YAxis tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} stroke="var(--border)" width={32} />
                <Tooltip
                  contentStyle={{
                    background: "var(--popover)",
                    color: "var(--popover-foreground)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "var(--popover-foreground)" }}
                  itemStyle={{ color: "var(--popover-foreground)" }}
                  labelFormatter={(_, p) => p?.[0]?.payload?.version ?? ""}
                />
                <Bar
                  dataKey="mean_reward"
                  fill="var(--chart-1)"
                  radius={[2, 2, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartBlock>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2 flex-wrap">
        <TrendingUp className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] text-muted-foreground">Policy:</span>
        <Badge variant="outline" className="font-mono text-[10px] border-primary/40 text-primary">
          {metrics?.policy_version ?? "ppo-v0.0.1"}
        </Badge>
        {policyVersions.length > 0 && (
          <span className="text-[10px] text-muted-foreground">
            · {policyVersions.length} snapshots
          </span>
        )}
      </div>
    </Card>
  );
}

function MetricTile({
  label, value, accent,
}: { label: string; value: string; accent: "primary" | "accent" | "destructive" | "muted" }) {
  const colorMap = {
    primary: "text-primary",
    accent: "text-accent",
    destructive: "text-destructive",
    muted: "text-muted-foreground",
  } as const;
  return (
    <motion.div
      initial={{ opacity: 0.6 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded-lg border border-border bg-background/40 p-3"
    >
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={`text-xl font-mono font-semibold mt-0.5 ${colorMap[accent]}`}>
        {value}
      </div>
    </motion.div>
  );
}

function ChartBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-3">
      <div className="text-[11px] text-muted-foreground mb-2">{title}</div>
      {children}
    </div>
  );
}
