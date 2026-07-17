"use client";

import { useEffect, useRef, useMemo } from "react";
import * as d3 from "d3";
import type { AgentStatus, AgentName } from "@/lib/aura/types";

interface GraphNode extends d3.SimulationNodeDatum {
  id: AgentName;
  label: string;
  role: string;
  status: string;
  latency: number | null;
  group: "core" | "specialist";
}

interface GraphLink extends d3.SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  kind: "control" | "data";
}

const NODE_DEFS: { id: AgentName; label: string; role: string; group: "core" | "specialist" }[] = [
  { id: "orchestrator",    label: "Orchestrator",     role: "Coordinates the loop",       group: "core" },
  { id: "preference",      label: "Preference",       role: "Interests & habits",         group: "specialist" },
  { id: "context",         label: "Context",          role: "Time/weather/location",      group: "specialist" },
  { id: "memory",          label: "Memory",           role: "Long-term recall",           group: "specialist" },
  { id: "knowledge",       label: "Knowledge",        role: "RAG + KG",                   group: "specialist" },
  { id: "recommendation",  label: "Recommendation",   role: "CF + Neural + GNN + LLM",    group: "specialist" },
  { id: "rl",              label: "RL Learning",      role: "PPO policy",                 group: "specialist" },
  { id: "explanation",     label: "Explanation",      role: "Why / why-not",              group: "specialist" },
  { id: "safety",          label: "Safety",           role: "Bias / privacy / policy",    group: "specialist" },
];

const LINK_DEFS: { source: AgentName; target: AgentName; kind: "control" | "data" }[] = [
  // orchestrator controls every specialist
  ...NODE_DEFS.filter(n => n.id !== "orchestrator").map(n => ({
    source: "orchestrator" as AgentName,
    target: n.id as AgentName,
    kind: "control" as const,
  })),
  // data flow edges
  { source: "context",        target: "recommendation", kind: "data" },
  { source: "preference",     target: "recommendation", kind: "data" },
  { source: "memory",         target: "preference",     kind: "data" },
  { source: "memory",         target: "recommendation", kind: "data" },
  { source: "knowledge",      target: "recommendation", kind: "data" },
  { source: "knowledge",      target: "explanation",    kind: "data" },
  { source: "recommendation", target: "safety",         kind: "data" },
  { source: "safety",         target: "explanation",    kind: "data" },
  { source: "recommendation", target: "rl",             kind: "data" },
  { source: "rl",             target: "recommendation", kind: "data" },
  { source: "preference",     target: "memory",         kind: "data" },
];

interface Props {
  agents: AgentStatus[];
  activeAgent: AgentName | null;
  onSelect?: (a: AgentName) => void;
  /** Live streaming steps from useStreamingOrchestration — overrides agent
   *  status colors while an orchestration run is in flight. */
  liveSteps?: { agent: AgentName; status: "thinking" | "ready" }[];
}

export function AgentNetwork({ agents, activeAgent, onSelect, liveSteps }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const statusMap = useMemo(() => {
    const m: Record<string, AgentStatus> = {};
    for (const a of agents) m[a.name] = a;
    // If we have live streaming steps, override the status to reflect them
    if (liveSteps && liveSteps.length > 0) {
      for (const step of liveSteps) {
        m[step.agent] = {
          ...(m[step.agent] || {
            name: step.agent,
            role: "",
            status: step.status,
            last_run: null,
            latency_ms: null,
            detail: "",
          }),
          status: step.status,
        };
      }
    }
    return m;
  }, [agents, liveSteps]);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const W = svgRef.current!.clientWidth;
    const H = 460;
    svg.attr("viewBox", `0 0 ${W} ${H}`);

    // background grid
    const defs = svg.append("defs");
    const glow = defs.append("filter").attr("id", "aura-glow").attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%");
    glow.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
    const merge = glow.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    // arrow marker for data links
    const arrow = defs.append("marker")
      .attr("id", "arrow-data")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 22)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto");
    arrow.append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "var(--accent)")
      .attr("fill-opacity", 0.7);

    const nodes: GraphNode[] = NODE_DEFS.map(d => ({
      ...d,
      status: statusMap[d.id]?.status ?? "idle",
      latency: statusMap[d.id]?.latency_ms ?? null,
    }));
    const links: GraphLink[] = LINK_DEFS.map(l => ({ ...l }));

    const sim = d3.forceSimulation<GraphNode>(nodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(links)
        .id(d => d.id)
        .distance(l => l.kind === "control" ? 110 : 80)
        .strength(l => l.kind === "control" ? 0.25 : 0.7))
      .force("charge", d3.forceManyBody().strength(d => (d as GraphNode).group === "core" ? -380 : -180))
      .force("center", d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide<GraphNode>().radius(d => d.group === "core" ? 56 : 42));

    // links
    const link = svg.append("g").attr("stroke-linecap", "round")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", l => l.kind === "control" ? "var(--muted-foreground)" : "var(--accent)")
      .attr("stroke-opacity", l => l.kind === "control" ? 0.45 : 0.7)
      .attr("stroke-width", l => l.kind === "control" ? 1 : 1.5)
      .attr("stroke-dasharray", l => l.kind === "control" ? "3 4" : "none")
      .attr("marker-end", l => l.kind === "data" ? "url(#arrow-data)" : "none");

    // nodes group
    const node = svg.append("g")
      .selectAll<SVGGElement, GraphNode>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(d3.drag<any, GraphNode>()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        }));

    // outer halo for core
    node.filter(d => d.group === "core")
      .append("circle")
      .attr("r", 48)
      .attr("fill", "var(--primary)")
      .attr("fill-opacity", 0.1)
      .attr("stroke", "var(--primary)")
      .attr("stroke-opacity", 0.45)
      .attr("stroke-width", 1);

    // main circle
    node.append("circle")
      .attr("r", d => d.group === "core" ? 32 : 24)
      .attr("fill", d => {
        if (d.group === "core") return "var(--primary)";
        if (activeAgent === d.id) return "var(--accent)";
        return "var(--card)";
      })
      .attr("fill-opacity", d => (d.group === "core" ? 0.2 : activeAgent === d.id ? 0.2 : 1))
      .attr("stroke", d => {
        if (d.group === "core" || d.status === "ready") return "var(--primary)";
        if (activeAgent === d.id) return "var(--accent)";
        return "var(--border)";
      })
      .attr("stroke-opacity", d => (d.group === "core" || activeAgent === d.id ? 1 : d.status === "ready" ? 0.7 : 1))
      .attr("stroke-width", d => (d.group === "core" || activeAgent === d.id) ? 2 : 1)
      .attr("filter", d => (d.group === "core" || activeAgent === d.id) ? "url(#aura-glow)" : null);

    // status dot
    node.append("circle")
      .attr("r", 4)
      .attr("cx", d => d.group === "core" ? 22 : 16)
      .attr("cy", d => d.group === "core" ? -22 : -16)
      .attr("fill", d => d.status === "ready" ? "var(--primary)" : "var(--muted-foreground)");

    // label
    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", d => d.group === "core" ? 50 : 38)
      .attr("fill", "var(--foreground)")
      .attr("font-size", 11)
      .attr("font-weight", 500)
      .text(d => d.label);

    // latency badge under label
    node.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", d => d.group === "core" ? 64 : 50)
      .attr("fill", "var(--muted-foreground)")
      .attr("font-size", 9)
      .attr("font-family", "var(--font-geist-mono)")
      .text(d => d.latency != null ? `${d.latency}ms` : "");

    node.on("click", (_, d) => onSelect?.(d.id));

    sim.on("tick", () => {
      link
        .attr("x1", l => (l.source as GraphNode).x!)
        .attr("y1", l => (l.source as GraphNode).y!)
        .attr("x2", l => (l.target as GraphNode).x!)
        .attr("y2", l => (l.target as GraphNode).y!);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    return () => {
      sim.stop();
    };
  }, [statusMap, activeAgent, onSelect]);

  return (
    <div className="w-full">
      <svg ref={svgRef} className="w-full" style={{ height: 460 }} />
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground mt-2 px-2">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-full bg-primary" />
          ready
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-full bg-muted-foreground" />
          idle
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-6 h-px bg-accent/70" />
          data flow
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-6 h-px border-t border-dashed border-muted-foreground/50" />
          control
        </span>
      </div>
    </div>
  );
}
