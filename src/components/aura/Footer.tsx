"use client";

import { Github } from "lucide-react";
import Image from "next/image";

export function Footer() {
  return (
    <footer className="mt-auto border-t border-border bg-background/60 backdrop-blur-sm">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Image src="/logo.png" alt="AURA" width={18} height={18} className="h-[18px] w-[18px] object-contain" />
              <span className="font-semibold">AURA</span>
              <span className="text-[11px] text-muted-foreground">v0.1.0</span>
            </div>
            <p className="text-[12px] text-muted-foreground leading-relaxed max-w-sm">
              Autonomous User Recommendation & Reasoning Architecture — a multi-agent
              reinforcement learning platform powered by LLMs, MCP, long-term memory,
              and continuous learning.
            </p>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
              Tech Stack
            </div>
            <div className="grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
              <span>Python · FastAPI</span>
              <span>Next.js 16 · TS</span>
              <span>TailwindCSS</span>
              <span>Shadcn UI</span>
              <span>Framer Motion</span>
              <span>Recharts · D3.js</span>
              <span>PostgreSQL · Redis</span>
              <span>Qdrant · Kafka</span>
              <span>PPO · BGE-M3</span>
              <span>MLflow · Grafana</span>
            </div>
          </div>

          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
              Multi-Agent Loop
            </div>
            <ol className="text-[11px] text-muted-foreground space-y-0.5 list-decimal list-inside">
              <li>Context Agent gathers current state</li>
              <li>Memory + Preference agents build profile</li>
              <li>Knowledge agent grounds facts</li>
              <li>Recommendation agent ranks candidates</li>
              <li>Safety agent filters unsafe items</li>
              <li>Explanation agent produces rationale</li>
              <li>RL agent ingests reward → policy update</li>
            </ol>
          </div>
        </div>

        <div className="mt-6 pt-4 border-t border-border flex flex-wrap items-center justify-between gap-3 text-[11px] text-muted-foreground">
          <div>
            © {new Date().getFullYear()} AURA Project — built with the stack you specified.
          </div>
          <a
            href="#"
            className="flex items-center gap-1.5 hover:text-foreground transition-colors"
            onClick={(e) => e.preventDefault()}
          >
            <Github className="h-3.5 w-3.5" />
            Source
          </a>
        </div>
      </div>
    </footer>
  );
}
