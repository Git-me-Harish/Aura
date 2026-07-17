"use client";

/**
 * AURA — Theme toggle (light / dark / system).
 *
 * Uses next-themes. Renders a 3-way segmented control with Sun / Monitor /
 * Moon icons. Mounted-guard avoids SSR hydration mismatch.
 */
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon, Monitor } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function ThemeToggle() {
  const [mounted, setMounted] = useState(false);
  const { theme, setTheme } = useTheme();

  useEffect(() => setMounted(true), []);

  if (!mounted) {
    // Placeholder with the same dimensions to prevent layout shift
    return <div className="h-8 w-[72px] rounded-md bg-muted/40 animate-pulse" />;
  }

  const current = theme === "system" ? "system" : theme === "light" ? "light" : "dark";

  const options: { value: "light" | "dark" | "system"; icon: typeof Sun; label: string }[] = [
    { value: "light", icon: Sun,     label: "Light" },
    { value: "system", icon: Monitor, label: "System" },
    { value: "dark",  icon: Moon,    label: "Dark" },
  ];

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex items-center gap-0.5 rounded-md border border-border bg-background/60 backdrop-blur-sm p-0.5">
        {options.map(({ value, icon: Icon, label }) => {
          const active = current === value;
          return (
            <Tooltip key={value}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setTheme(value)}
                  aria-label={`Switch to ${label} theme`}
                  className={`flex items-center justify-center h-7 w-7 rounded transition-colors ${
                    active
                      ? "bg-primary/15 text-primary"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-[11px]">
                {label} mode
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
