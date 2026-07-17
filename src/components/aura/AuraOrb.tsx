"use client";

/**
 * AURA Orb — the interactive centerpiece of the hero section.
 *
 * Visual concept (inspired by the two reference images):
 *   1. Layered translucent diamond stack (image 1) — three isometric
 *      diamond-shaped panels, each representing one layer of AURA's
 *      intelligence (Memory → Knowledge → Decision).
 *   2. Network constellation hub (image 2) — a central pulsing "AURA" core
 *      with 4 pillar nodes radiating outward, connected by glowing lines.
 *
 * Interaction:
 *   - Hovering a pillar node highlights it and shows a tooltip with that
 *     pillar's role + the agent that powers it.
 *   - Clicking the central AURA core triggers orchestration (same as the
 *     "Run Orchestration" button below).
 *   - While orchestration is running, the orb pulses faster and the
 *     constellation lines "flow" toward the active pillar.
 *
 * The 4 pillars map directly to AURA's mission statement:
 *   - Why?            → Recommendation Agent (CF + Neural CF + blend)
 *   - When?           → Context Agent (time / weather / calendar / mood)
 *   - How Confident?  → Memory + Knowledge (retrieval-grounded certainty)
 *   - How to Improve? → RL Agent (PPO, reward signal, policy updates)
 */
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Brain, Clock, Gauge, TrendingUp } from "lucide-react";

interface Props {
  onRun: () => void;
  running: boolean;
}

type PillarId = "why" | "when" | "confident" | "improve";

interface Pillar {
  id: PillarId;
  label: string;
  question: string;
  agent: string;
  detail: string;
  icon: typeof Brain;
  color: string;       // oklch color string
  // Position on the 320×320 SVG canvas (center is 160,160)
  x: number;
  y: number;
}

const PILLARS: Pillar[] = [
  {
    id: "why",
    label: "Why",
    question: "Why recommend?",
    agent: "Recommendation Agent",
    detail: "ALS collaborative filtering + Neural CF (GMF+MLP) + context blend produce ranked candidates with per-item score breakdown.",
    icon: Brain,
    color: "oklch(0.72 0.18 155)",  // emerald
    x: 160,
    y: 30,
  },
  {
    id: "when",
    label: "When",
    question: "When?",
    agent: "Context Agent",
    detail: "Time-of-day, day-of-week, weather, calendar, and mood shape a context vector that re-weights the candidate blend in real time.",
    icon: Clock,
    color: "oklch(0.78 0.16 75)",   // amber
    x: 290,
    y: 160,
  },
  {
    id: "confident",
    label: "Confident",
    question: "How confident?",
    agent: "Memory + Knowledge",
    detail: "Long-term memory + Qdrant hybrid retrieval (BM25 + dense) ground each recommendation in user history and factual knowledge.",
    icon: Gauge,
    color: "oklch(0.80 0.13 195)",  // teal
    x: 160,
    y: 290,
  },
  {
    id: "improve",
    label: "Improve",
    question: "How to improve?",
    agent: "RL Agent (PPO)",
    detail: "Every click / like / skip / purchase becomes a reward signal. PPO trains the policy on a 10-step cadence and ships a new version.",
    icon: TrendingUp,
    color: "oklch(0.62 0.16 305)",  // violet
    x: 30,
    y: 160,
  },
];

export function AuraOrb({ onRun, running }: Props) {
  const [hovered, setHovered] = useState<PillarId | null>(null);

  const activePillar = PILLARS.find((p) => p.id === hovered) || null;

  return (
    <div className="relative w-full aspect-square max-w-[420px] mx-auto select-none">
      {/* Ambient glow */}
      <div
        className="absolute inset-0 rounded-full blur-3xl opacity-40 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 50% 50%, var(--primary), transparent 60%)",
        }}
      />

      <svg
        viewBox="0 0 320 320"
        className="relative w-full h-full"
        role="img"
        aria-label="AURA Orb — interactive visualization of the four pillars: Why, When, How Confident, How to Improve"
      >
        <defs>
          {/* Diamond gradients */}
          <linearGradient id="diamondTop" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.15" />
          </linearGradient>
          <linearGradient id="diamondMid" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.15" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.10" />
          </linearGradient>
          <linearGradient id="diamondBot" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="oklch(0.62 0.16 305)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.30" />
          </linearGradient>
          <radialGradient id="coreGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.90" />
            <stop offset="60%" stopColor="var(--primary)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
          </radialGradient>

          {/* Connection line gradient */}
          <linearGradient id="lineFlow" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.0" />
            <stop offset="50%" stopColor="var(--primary)" stopOpacity="0.8" />
            <stop offset="100%" stopColor="var(--primary)" stopOpacity="0.0" />
          </linearGradient>
        </defs>

        {/* Background grid (subtle) */}
        <g opacity="0.10">
          {Array.from({ length: 7 }).map((_, i) => (
            <line
              key={`h${i}`}
              x1="0" y1={i * 50 + 10}
              x2="320" y2={i * 50 + 10}
              stroke="currentColor"
              strokeWidth="0.5"
              className="text-foreground"
            />
          ))}
          {Array.from({ length: 7 }).map((_, i) => (
            <line
              key={`v${i}`}
              x1={i * 50 + 10} y1="0"
              x2={i * 50 + 10} y2="320"
              stroke="currentColor"
              strokeWidth="0.5"
              className="text-foreground"
            />
          ))}
        </g>

        {/* Three isometric layered diamonds (background depth) */}
        {/* Bottom layer (largest, warmest) */}
        <motion.path
          d="M 160 240 L 280 160 L 160 80 L 40 160 Z"
          fill="url(#diamondBot)"
          stroke="oklch(0.62 0.16 305)"
          strokeWidth="1"
          strokeOpacity="0.4"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.1 }}
          style={{ transformOrigin: "160px 160px" }}
        />
        {/* Middle layer */}
        <motion.path
          d="M 160 220 L 255 160 L 160 100 L 65 160 Z"
          fill="url(#diamondMid)"
          stroke="var(--primary)"
          strokeWidth="1"
          strokeOpacity="0.5"
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        />
        {/* Top layer (smallest, brightest) */}
        <motion.path
          d="M 160 200 L 230 160 L 160 120 L 90 160 Z"
          fill="url(#diamondTop)"
          stroke="var(--primary)"
          strokeWidth="1.2"
          strokeOpacity="0.7"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3 }}
        />

        {/* Floating data dots above the top diamond (from image 1) */}
        {[
          { x: 130, y: 95, r: 1.5, c: "var(--primary)", d: 0.6 },
          { x: 145, y: 85, r: 1, c: "var(--accent)", d: 0.7 },
          { x: 175, y: 88, r: 1.8, c: "var(--primary)", d: 0.5 },
          { x: 195, y: 100, r: 1.2, c: "oklch(0.62 0.16 305)", d: 0.8 },
          { x: 160, y: 75, r: 1, c: "var(--accent)", d: 0.9 },
          { x: 115, y: 110, r: 1.3, c: "var(--primary)", d: 1.0 },
        ].map((dot, i) => (
          <motion.circle
            key={`dot-${i}`}
            cx={dot.x} cy={dot.y} r={dot.r}
            fill={dot.c}
            initial={{ opacity: 0, scale: 0 }}
            animate={{
              opacity: [0.4, 1, 0.4],
              scale: [0.8, 1.2, 0.8],
              y: [dot.y, dot.y - 4, dot.y],
            }}
            transition={{
              duration: dot.d * 2,
              repeat: Infinity,
              ease: "easeInOut",
              delay: i * 0.15,
            }}
          />
        ))}

        {/* Connection lines: core → 4 pillars */}
        {PILLARS.map((p) => {
          const isActive = hovered === p.id;
          return (
            <motion.line
              key={`line-${p.id}`}
              x1="160" y1="160"
              x2={p.x} y2={p.y}
              stroke={isActive ? p.color : "var(--border)"}
              strokeWidth={isActive ? 1.5 : 0.8}
              strokeOpacity={isActive ? 0.9 : 0.5}
              strokeDasharray="3 3"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{
                pathLength: 1,
                opacity: running ? [0.3, 1, 0.3] : 1,
              }}
              transition={{
                pathLength: { duration: 0.6, delay: 0.4 },
                opacity: running
                  ? { duration: 1, repeat: Infinity, ease: "easeInOut" }
                  : { duration: 0.3 },
              }}
            />
          );
        })}

        {/* Central AURA core — clickable */}
        <motion.g
          onClick={onRun}
          className="cursor-pointer"
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          initial={{ opacity: 0, scale: 0 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.5, type: "spring" }}
        >
          {/* Outer glow */}
          <motion.circle
            cx="160" cy="160" r="50"
            fill="url(#coreGlow)"
            animate={{
              r: running ? [50, 60, 50] : [50, 55, 50],
              opacity: running ? [0.6, 1, 0.6] : [0.4, 0.7, 0.4],
            }}
            transition={{
              duration: running ? 1.2 : 3,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
          {/* Solid core */}
          <circle
            cx="160" cy="160" r="32"
            fill="var(--background)"
            stroke="var(--primary)"
            strokeWidth="1.5"
          />
          {/* Inner ring */}
          <motion.circle
            cx="160" cy="160" r="26"
            fill="none"
            stroke="var(--primary)"
            strokeWidth="0.8"
            strokeOpacity="0.5"
            strokeDasharray="4 2"
            animate={{ rotate: 360 }}
            transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
            style={{ transformOrigin: "160px 160px" }}
          />
          <image
            href="/logo.png"
            x="146"
            y="142"
            width="28"
            height="28"
            preserveAspectRatio="xMidYMid meet"
          />
          <text
            x="160" y="178"
            textAnchor="middle"
            className="fill-muted-foreground"
            style={{ fontSize: "6px", letterSpacing: "0.3px" }}
          >
            {running ? "ORCHESTRATING" : "TAP TO RUN"}
          </text>
        </motion.g>

        {/* 4 pillar nodes */}
        {PILLARS.map((p) => {
          const isActive = hovered === p.id;
          const Icon = p.icon;
          return (
            <motion.g
              key={p.id}
              onMouseEnter={() => setHovered(p.id)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => setHovered(p.id)}
              className="cursor-pointer"
              initial={{ opacity: 0, scale: 0 }}
              animate={{
                opacity: 1,
                scale: isActive ? 1.15 : 1,
              }}
              transition={{ duration: 0.4, delay: 0.6, type: "spring" }}
            >
              {/* Glow halo */}
              <motion.circle
                cx={p.x} cy={p.y} r="22"
                fill={p.color}
                fillOpacity={isActive ? 0.30 : 0.10}
                animate={{
                  r: isActive ? [22, 28, 22] : 22,
                }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              />
              {/* Solid node */}
              <circle
                cx={p.x} cy={p.y} r="16"
                fill="var(--background)"
                stroke={p.color}
                strokeWidth="1.5"
              />
              {/* Pillar icon */}
              <foreignObject
                x={p.x - 10} y={p.y - 10}
                width="20" height="20"
                style={{ pointerEvents: "none" }}
              >
                <div className="w-full h-full flex items-center justify-center">
                  <Icon
                    className="w-4 h-4"
                    style={{ color: p.color }}
                  />
                </div>
              </foreignObject>
              {/* Label */}
              <text
                x={p.x}
                y={p.y + 32}
                textAnchor="middle"
                className="fill-foreground"
                style={{
                  fontSize: "10px",
                  fontWeight: isActive ? 700 : 500,
                }}
              >
                {p.label}
              </text>
            </motion.g>
          );
        })}

        {/* Tiny data-flow particles along the connection lines (only when running) */}
        {running &&
          PILLARS.map((p, i) => (
            <motion.circle
              key={`particle-${p.id}`}
              r="1.5"
              fill="var(--primary)"
              initial={{ cx: 160, cy: 160, opacity: 0 }}
              animate={{
                cx: [160, p.x],
                cy: [160, p.y],
                opacity: [0, 1, 0],
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                delay: i * 0.3,
                ease: "easeInOut",
              }}
            />
          ))}
      </svg>

      {/* Hover tooltip overlay (positioned absolutely) */}
      <AnimatePresence>
        {activePillar && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[90%] max-w-[360px]"
          >
            <div
              className="rounded-lg border bg-card/95 backdrop-blur-md p-3 shadow-xl"
              style={{ borderColor: `color-mix(in oklch, ${activePillar.color} 40%, var(--border))` }}
            >
              <div className="flex items-center gap-2 mb-1">
                <activePillar.icon
                  className="w-3.5 h-3.5"
                  style={{ color: activePillar.color }}
                />
                <span
                  className="text-xs font-semibold"
                  style={{ color: activePillar.color }}
                >
                  {activePillar.question}
                </span>
                <span className="text-[10px] text-muted-foreground ml-auto">
                  {activePillar.agent}
                </span>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                {activePillar.detail}
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
