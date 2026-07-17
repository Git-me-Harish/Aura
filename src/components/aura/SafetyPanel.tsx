"use client";

import { motion } from "framer-motion";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SafetyVerdict } from "@/lib/aura/types";

interface Props {
  verdicts: SafetyVerdict[];
}

const FLAG_LABELS: { key: keyof SafetyVerdict; label: string }[] = [
  { key: "bias_flag",         label: "Bias" },
  { key: "unsafe_flag",       label: "Unsafe" },
  { key: "hallucination_flag",label: "Hallucination" },
  { key: "privacy_flag",      label: "Privacy" },
  { key: "policy_flag",       label: "Policy" },
];

export function SafetyPanel({ verdicts }: Props) {
  const passed = verdicts.filter(v => v.passed).length;
  const flagged = verdicts.filter(v => !v.passed);

  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Safety Agent</h3>
          <p className="text-[11px] text-muted-foreground">
            Bias · unsafe · hallucination · privacy · policy compliance
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[11px]">
          <span className="text-primary mr-1">{passed}</span>
          /{verdicts.length} passed
        </Badge>
      </div>

      {verdicts.length === 0 ? (
        <div className="py-8 text-center text-sm text-muted-foreground">
          No safety verdicts yet.
        </div>
      ) : (
        <div className="space-y-2 max-h-[260px] overflow-y-auto scroll-thin pr-1">
          {verdicts.map((v, i) => (
            <motion.div
              key={v.item_id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: i * 0.03 }}
              className="rounded-lg border border-border bg-background/40 p-2.5"
            >
              <div className="flex items-center gap-2">
                {v.passed ? (
                  <ShieldCheck className="h-3.5 w-3.5 text-primary shrink-0" />
                ) : (
                  <ShieldAlert className="h-3.5 w-3.5 text-destructive shrink-0" />
                )}
                <span className="text-[12px] font-mono truncate">{v.item_id}</span>
                <div className="ml-auto flex gap-1 flex-wrap justify-end">
                  {FLAG_LABELS.map(f => v[f.key] ? (
                    <Badge
                      key={f.key}
                      variant="outline"
                      className="text-[9px] py-0 px-1 border-destructive/50 text-destructive"
                    >
                      {f.label}
                    </Badge>
                  ) : null)}
                </div>
              </div>
              {v.notes && !v.passed && (
                <p className="text-[11px] text-muted-foreground mt-1.5 pl-5">
                  {v.notes}
                </p>
              )}
            </motion.div>
          ))}
        </div>
      )}
    </Card>
  );
}
