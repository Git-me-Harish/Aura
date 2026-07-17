"use client";

import { motion, AnimatePresence } from "framer-motion";
import {
  ThumbsUp,
  ShoppingCart,
  Eye,
  SkipForward,
  Loader2,
  ShieldCheck,
  Activity,
  Brain,
  Clock,
  Sparkles,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { RecommendationItem, Explanation, SafetyVerdict } from "@/lib/aura/types";

interface Props {
  items: RecommendationItem[];
  explanations: Explanation[];
  safety: SafetyVerdict[];
  loading: boolean;
  onAction: (itemId: string, action: "click" | "like" | "purchase" | "skip") => void;
  pendingItemId: string | null;
}

const SOURCE_COLOR: Record<string, string> = {
  cf:        "text-chart-5 border-chart-5/40 bg-chart-5/10",
  neural_cf: "text-chart-1 border-chart-1/40 bg-chart-1/10",
  hybrid:    "text-primary border-primary/40 bg-primary/10",
  gnn:       "text-chart-4 border-chart-4/40 bg-chart-4/10",
  llm_rank:  "text-chart-2 border-chart-2/40 bg-chart-2/10",
};

const CAT_COLOR: Record<string, string> = {
  tech: "oklch(0.72 0.18 155)",
  music: "oklch(0.78 0.16 75)",
  movies: "oklch(0.65 0.22 18)",
  fitness: "oklch(0.62 0.16 305)",
  food: "oklch(0.80 0.13 195)",
  books: "oklch(0.72 0.18 155)",
  finance: "oklch(0.78 0.16 75)",
};

interface ScoreBit {
  key: string;
  label: string;
  value: number;
  weight: number;
  icon: React.ReactNode;
  color: string;
}

function scoreBits(meta: Record<string, any>): ScoreBit[] {
  const cf = typeof meta.cf_score === "number" ? meta.cf_score : null;
  const ncf = typeof meta.neural_cf_score === "number" ? meta.neural_cf_score : null;
  const ctx = typeof meta.context_score === "number" ? meta.context_score : null;
  const rlP = typeof meta.rl_p === "number" ? meta.rl_p : null;

  const bits: ScoreBit[] = [];
  if (cf !== null) {
    bits.push({
      key: "cf",
      label: "ALS CF",
      value: cf,
      weight: 0.40,
      icon: <Activity className="h-3 w-3" />,
      color: "oklch(0.72 0.18 155)",
    });
  }
  if (ncf !== null) {
    bits.push({
      key: "ncf",
      label: "Neural CF",
      value: ncf,
      weight: 0.30,
      icon: <Brain className="h-3 w-3" />,
      color: "oklch(0.78 0.16 75)",
    });
  }
  if (ctx !== null) {
    bits.push({
      key: "ctx",
      label: "Context",
      value: ctx,
      weight: 0.20,
      icon: <Clock className="h-3 w-3" />,
      color: "oklch(0.80 0.13 195)",
    });
  }
  if (rlP !== null) {
    bits.push({
      key: "rl",
      label: "RL policy",
      value: rlP,
      weight: 0.10,
      icon: <Sparkles className="h-3 w-3" />,
      color: "oklch(0.62 0.16 305)",
    });
  }
  return bits;
}

function ScoreBreakdown({ meta }: { meta: Record<string, any> }) {
  const bits = scoreBits(meta);
  if (bits.length === 0) return null;

  return (
    <TooltipProvider delayDuration={150}>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {bits.map((b) => (
          <Tooltip key={b.key}>
            <TooltipTrigger asChild>
              <div
                className="group flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-mono cursor-help"
                style={{
                  borderColor: `${b.color}55`,
                  background: `${b.color}10`,
                  color: b.color,
                }}
              >
                <span className="opacity-80">{b.icon}</span>
                <span className="font-medium">{b.label}</span>
                <span className="tabular-nums">{b.value.toFixed(2)}</span>
                <span className="opacity-50">×{b.weight}</span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-[11px]">
              <div className="font-medium">{b.label}</div>
              <div className="text-muted-foreground">
                raw = {b.value.toFixed(4)}, weight = {b.weight}
              </div>
              <div className="text-muted-foreground">
                contribution = {(b.value * b.weight).toFixed(4)}
              </div>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}

export function RecommendationsPanel({
  items,
  explanations,
  safety,
  loading,
  onAction,
  pendingItemId,
}: Props) {
  const explMap = new Map(explanations.map((e) => [e.item_id, e]));
  const safetyMap = new Map(safety.map((s) => [s.item_id, s]));

  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Live Recommendations</h3>
          <p className="text-[11px] text-muted-foreground">
            Candidates produced by the Recommendation Agent, filtered by Safety.
            Each card shows the live ranker breakdown (ALS CF · Neural CF ·
            Context · RL policy).
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[11px]">
          {items.length} items
        </Badge>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-lg bg-muted/40 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">
          No recommendations yet. Run an orchestration to see live candidates.
        </div>
      ) : (
        <div className="space-y-3 max-h-[640px] overflow-y-auto scroll-thin pr-1">
          <AnimatePresence mode="popLayout">
            {items.map((item, idx) => {
              const expl = explMap.get(item.item_id);
              const sv = safetyMap.get(item.item_id);
              const catColor = CAT_COLOR[item.category] ?? "oklch(0.72 0.18 155)";
              return (
                <motion.div
                  key={item.item_id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.25, delay: idx * 0.04 }}
                  className="rounded-lg border border-border bg-background/40 p-3 hover:border-primary/40 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ background: catColor }}
                        />
                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          {item.category}
                        </span>
                        <Badge
                          variant="outline"
                          className={`text-[10px] py-0 px-1.5 ${SOURCE_COLOR[item.source] ?? ""}`}
                        >
                          {item.source}
                        </Badge>
                        {sv?.passed ? (
                          <Badge
                            variant="outline"
                            className="text-[10px] py-0 px-1.5 border-primary/40 text-primary"
                          >
                            <ShieldCheck className="h-3 w-3 mr-1" /> safe
                          </Badge>
                        ) : sv && !sv.passed ? (
                          <Badge
                            variant="outline"
                            className="text-[10px] py-0 px-1.5 border-destructive/50 text-destructive"
                          >
                            flagged
                          </Badge>
                        ) : null}
                      </div>
                      <h4 className="text-sm font-medium mt-1.5 truncate">
                        {item.title}
                      </h4>
                      <p className="text-[12px] text-muted-foreground mt-0.5 line-clamp-2">
                        {item.description}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-[10px] text-muted-foreground">score</div>
                      <div className="text-lg font-mono font-semibold text-primary">
                        {item.score.toFixed(2)}
                      </div>
                    </div>
                  </div>

                  <div className="mt-2.5">
                    <Progress value={item.score * 100} className="h-1" />
                  </div>

                  {/* ── Ranker score breakdown (cf / neural_cf / context / RL) ── */}
                  <ScoreBreakdown meta={item.metadata} />

                  {item.reasons && item.reasons.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {item.reasons.slice(0, 3).map((r, i) => (
                        <span
                          key={i}
                          className="text-[10px] text-muted-foreground bg-muted/40 rounded px-1.5 py-0.5"
                        >
                          {r}
                        </span>
                      ))}
                    </div>
                  )}

                  {expl && (
                    <div className="mt-2.5 text-[11px] text-muted-foreground leading-relaxed">
                      <span className="text-foreground/80 font-medium">Why: </span>
                      {expl.why_recommended}
                    </div>
                  )}

                  <div className="mt-3 flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-[11px] px-2"
                      onClick={() => onAction(item.item_id, "click")}
                      disabled={pendingItemId === item.item_id}
                    >
                      {pendingItemId === item.item_id ? (
                        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      ) : (
                        <Eye className="h-3 w-3 mr-1" />
                      )}
                      Click
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-[11px] px-2"
                      onClick={() => onAction(item.item_id, "like")}
                      disabled={pendingItemId === item.item_id}
                    >
                      <ThumbsUp className="h-3 w-3 mr-1" /> Like
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-[11px] px-2"
                      onClick={() => onAction(item.item_id, "purchase")}
                      disabled={pendingItemId === item.item_id}
                    >
                      <ShoppingCart className="h-3 w-3 mr-1" /> Buy
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 text-[11px] px-2 text-muted-foreground"
                      onClick={() => onAction(item.item_id, "skip")}
                      disabled={pendingItemId === item.item_id}
                    >
                      <SkipForward className="h-3 w-3 mr-1" /> Skip
                    </Button>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </Card>
  );
}
