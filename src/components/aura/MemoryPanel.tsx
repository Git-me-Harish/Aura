"use client";

import { motion } from "framer-motion";
import { Brain, Clock, MessageSquare, ShoppingBag, Hash } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { MemoryRecord } from "@/lib/aura/types";

const KIND_ICON: Record<string, any> = {
  preference: Brain,
  interaction: Clock,
  conversation: MessageSquare,
  purchase: ShoppingBag,
  embedding: Hash,
};

const KIND_COLOR: Record<string, string> = {
  preference: "text-primary border-primary/40 bg-primary/10",
  interaction: "text-chart-5 border-chart-5/40 bg-chart-5/10",
  conversation: "text-chart-4 border-chart-4/40 bg-chart-4/10",
  purchase: "text-accent border-accent/40 bg-accent/10",
  embedding: "text-muted-foreground border-border bg-muted/20",
};

interface Props {
  records: MemoryRecord[];
}

export function MemoryPanel({ records }: Props) {
  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm h-full">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Long-Term Memory</h3>
          <p className="text-[11px] text-muted-foreground">
            Vector DB (Qdrant) · hybrid BM25 + dense retrieval
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[11px]">
          {records.length} records
        </Badge>
      </div>

      {records.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">
          No memories recalled yet.
        </div>
      ) : (
        <div className="space-y-2 max-h-[420px] overflow-y-auto scroll-thin pr-1">
          {records.map((r, i) => {
            const Icon = KIND_ICON[r.kind] ?? Hash;
            return (
              <motion.div
                key={r.record_id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: i * 0.04 }}
                className="rounded-lg border border-border bg-background/40 p-2.5"
              >
                <div className="flex items-start gap-2">
                  <div className="h-6 w-6 rounded-md bg-muted/40 flex items-center justify-center shrink-0 mt-0.5">
                    <Icon className="h-3 w-3 text-muted-foreground" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-1">
                      <Badge
                        variant="outline"
                        className={`text-[9px] py-0 px-1.5 ${KIND_COLOR[r.kind] ?? ""}`}
                      >
                        {r.kind}
                      </Badge>
                      <span className="text-[9px] text-muted-foreground/70 font-mono">
                        {r.timestamp ? new Date(r.timestamp).toLocaleString() : ""}
                      </span>
                    </div>
                    <p className="text-[12px] leading-snug text-foreground/90">
                      {r.content}
                    </p>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
