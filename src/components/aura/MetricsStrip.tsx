"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Gauge, Users, Target, TrendingUp, DollarSign, Clock } from "lucide-react";
import type { DashboardMetrics } from "@/lib/aura/types";

interface Props {
  metrics: DashboardMetrics | null;
}

export function MetricsStrip({ metrics }: Props) {
  if (!metrics) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="p-3 bg-card/40 animate-pulse h-20" />
        ))}
      </div>
    );
  }

  const tiles = [
    { label: "NDCG",        value: metrics.recommendation.ndcg.toFixed(3),           icon: Target,      accent: "text-primary" },
    { label: "Precision@K", value: metrics.recommendation.precision_at_k.toFixed(3), icon: Gauge,       accent: "text-chart-5" },
    { label: "MRR",         value: metrics.recommendation.mrr.toFixed(3),            icon: TrendingUp,  accent: "text-accent" },
    { label: "CTR",         value: (metrics.business.ctr * 100).toFixed(1) + "%",    icon: Users,       accent: "text-chart-4" },
    { label: "Revenue",     value: "$" + metrics.business.revenue.toLocaleString(),   icon: DollarSign,  accent: "text-primary" },
    { label: "Avg Session", value: Math.round(metrics.business.avg_session_time_sec) + "s", icon: Clock, accent: "text-accent" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {tiles.map((t, i) => (
        <motion.div
          key={t.label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: i * 0.04 }}
        >
          <Card className="p-3 bg-card/60 backdrop-blur-sm">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                {t.label}
              </span>
              <t.icon className={`h-3 w-3 ${t.accent}`} />
            </div>
            <div className={`text-lg font-mono font-semibold ${t.accent}`}>
              {t.value}
            </div>
          </Card>
        </motion.div>
      ))}
    </div>
  );
}
