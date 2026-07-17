"use client";

/**
 * AURA — Session + Theme providers.
 *
 * SessionProvider: enables useSession() across the app.
 * ThemeProvider:   next-themes — light/dark/system toggle.
 */
import { SessionProvider } from "next-auth/react";
import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem
        disableTransitionOnChange
      >
        {children}
      </ThemeProvider>
    </SessionProvider>
  );
}
