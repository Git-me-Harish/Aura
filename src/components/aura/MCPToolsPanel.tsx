"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Calendar, Mail, Github, Music, MapPin, CloudSun,
  Newspaper, LineChart, ShoppingBag, HeartPulse, Slack,
  FileText, HardDrive, Database, Loader2, CheckCircle2, XCircle,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { MCPTool } from "@/lib/aura/types";

const ICONS: Record<string, any> = {
  calendar: Calendar, email: Mail, github: Github, spotify: Music,
  maps: MapPin, weather: CloudSun, news: Newspaper, finance: LineChart,
  shopping: ShoppingBag, health: HeartPulse, slack: Slack, notion: FileText,
  drive: HardDrive, databricks: Database,
};

interface Props {
  tools: MCPTool[];
  onInvoke: (tool: string, method: string) => void;
  pendingTool: string | null;
  lastResult: Record<string, any>;
}

export function MCPToolsPanel({ tools, onInvoke, pendingTool, lastResult }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const connected = tools.filter(t => t.connected);
  const disconnected = tools.filter(t => !t.connected);

  return (
    <Card className="p-4 sm:p-5 bg-card/60 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold">MCP Tool Layer</h3>
          <p className="text-[11px] text-muted-foreground">
            Model Context Protocol servers — external tools the agents call
          </p>
        </div>
        <Badge variant="outline" className="font-mono text-[11px]">
          <span className="text-primary mr-1">{connected.length}</span>
          /{tools.length}
        </Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[460px] overflow-y-auto scroll-thin pr-1">
        {[...connected, ...disconnected].map((tool, idx) => {
          const Icon = ICONS[tool.category] ?? Database;
          const isPending = pendingTool === tool.name;
          const result = lastResult[tool.name];
          return (
            <motion.div
              key={tool.name}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: idx * 0.03 }}
              className="rounded-lg border border-border bg-background/40 p-2.5"
            >
              <div className="flex items-center gap-2">
                <div
                  className={`h-7 w-7 rounded-md flex items-center justify-center ${
                    tool.connected
                      ? "bg-primary/15 text-primary"
                      : "bg-muted/40 text-muted-foreground"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[12px] font-medium capitalize">{tool.name}</span>
                    {tool.connected ? (
                      <CheckCircle2 className="h-3 w-3 text-primary" />
                    ) : (
                      <XCircle className="h-3 w-3 text-muted-foreground/60" />
                    )}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    {tool.description}
                  </div>
                </div>
              </div>

              {tool.connected && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {tool.capabilities.slice(0, 3).map(cap => (
                    <Button
                      key={cap}
                      size="sm"
                      variant="outline"
                      disabled={isPending}
                      onClick={() => {
                        onInvoke(tool.name, cap);
                        setExpanded(tool.name);
                      }}
                      className="h-6 text-[10px] px-1.5 font-mono"
                    >
                      {isPending ? (
                        <Loader2 className="h-2.5 w-2.5 mr-1 animate-spin" />
                      ) : null}
                      {cap}
                    </Button>
                  ))}
                </div>
              )}

              {expanded === tool.name && result && (
                <pre className="mt-2 text-[10px] text-muted-foreground bg-muted/30 rounded p-2 max-h-32 overflow-auto scroll-thin font-mono">
                  {JSON.stringify(result, null, 2)}
                </pre>
              )}
            </motion.div>
          );
        })}
      </div>
    </Card>
  );
}
