"use client";

import { motion } from "framer-motion";
import { Activity, Cpu } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { UserMenu } from "@/components/auth/user-menu";
import { ThemeToggle } from "@/components/aura/ThemeToggle";
import Link from "next/link";
import Image from "next/image";

interface Props {
  policyVersion: string | null;
  samplesSeen: number;
  agentsReady: number;
  totalAgents: number;
  rlBackend?: string;
  llmProvider?: string;
}

export function Header({
  policyVersion, samplesSeen, agentsReady, totalAgents,
  rlBackend, llmProvider,
}: Props) {
  return (
    <header className="sticky top-0 z-30 backdrop-blur-xl bg-background/70 border-b border-border">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link href="/" aria-label="AURA home">
            <motion.div
              initial={{ rotate: -90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              transition={{ duration: 0.6, ease: "easeOut" }}
              className="relative h-9 w-9 rounded-lg bg-primary/15 border border-primary/40 flex items-center justify-center"
            >
              <Image src="/logo.png" alt="AURA" width={28} height={28} priority className="h-7 w-7 object-contain" />
              <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-primary animate-pulse" />
            </motion.div>
          </Link>
          <div className="leading-tight">
            <div className="flex items-center gap-2">
              <Link href="/" className="text-base font-semibold tracking-tight text-glow">AURA</Link>
              <Badge variant="outline" className="text-[10px] py-0 px-1.5 border-primary/40 text-primary">
                v0.2
              </Badge>
              {llmProvider && llmProvider !== "none" && (
                <Badge variant="outline" className="text-[9px] py-0 px-1.5 hidden sm:inline-flex">
                  LLM: {llmProvider}
                </Badge>
              )}
              {rlBackend && (
                <Badge variant="outline" className="text-[9px] py-0 px-1.5 hidden sm:inline-flex text-accent border-accent/40">
                  RL: {rlBackend}
                </Badge>
              )}
            </div>
            <span className="text-[11px] text-muted-foreground hidden sm:inline">
              Autonomous User Recommendation & Reasoning Architecture
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3 sm:gap-5 text-xs">
          <div className="hidden md:flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5 text-primary" />
            <span className="text-muted-foreground">Agents</span>
            <span className="font-mono">
              <span className="text-primary">{agentsReady}</span>
              <span className="text-muted-foreground">/{totalAgents}</span>
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-1.5">
            <Cpu className="h-3.5 w-3.5 text-accent" />
            <span className="text-muted-foreground">Samples</span>
            <span className="font-mono text-accent">{samplesSeen}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            <span className="font-mono text-[11px] text-muted-foreground">
              {policyVersion ?? "—"}
            </span>
          </div>
          <ThemeToggle />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
