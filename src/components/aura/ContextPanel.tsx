"use client";

import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Clock, CloudSun, MapPin, Smartphone, Smile, Search, CalendarClock,
} from "lucide-react";
import type { ContextSnapshot } from "@/lib/aura/types";

interface Props {
  ctx: ContextSnapshot | null;
}

export function ContextPanel({ ctx }: Props) {
  if (!ctx) {
    return (
      <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm h-full">
        <h3 className="text-sm font-semibold mb-3">Context Snapshot</h3>
        <div className="py-8 text-center text-sm text-muted-foreground">
          No context yet.
        </div>
      </Card>
    );
  }

  const items = [
    { icon: Clock,         label: "Time",        value: `${ctx.weekday} · ${ctx.time_of_day}` },
    { icon: CloudSun,      label: "Weather",     value: `${ctx.weather} · ${ctx.temperature_c}°C` },
    { icon: MapPin,        label: "Location",    value: ctx.location },
    { icon: Smartphone,    label: "Device",      value: ctx.device },
    { icon: Smile,         label: "Mood",        value: ctx.mood },
    { icon: CalendarClock, label: "Next event",  value: ctx.calendar_next ?? "—" },
  ];

  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm h-full">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">Context Snapshot</h3>
          <p className="text-[11px] text-muted-foreground">
            What is happening right now — gathered via MCP tools
          </p>
        </div>
        <Badge variant="outline" className="text-[10px] font-mono">
          {new Date(ctx.timestamp).toLocaleTimeString()}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        {items.map((it, i) => (
          <motion.div
            key={it.label}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, delay: i * 0.04 }}
            className="rounded-md border border-border bg-background/40 p-2"
          >
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <it.icon className="h-3 w-3" />
              <span className="text-[10px] uppercase tracking-wider">{it.label}</span>
            </div>
            <div className="text-[12px] mt-0.5 truncate capitalize">{it.value}</div>
          </motion.div>
        ))}
      </div>

      <div className="rounded-md border border-border bg-background/40 p-2.5">
        <div className="flex items-center gap-1.5 text-muted-foreground mb-1.5">
          <Search className="h-3 w-3" />
          <span className="text-[10px] uppercase tracking-wider">Recent searches</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ctx.recent_searches.map(s => (
            <Badge
              key={s}
              variant="outline"
              className="text-[10px] py-0 px-1.5 font-mono text-muted-foreground"
            >
              {s}
            </Badge>
          ))}
        </div>
      </div>
    </Card>
  );
}
