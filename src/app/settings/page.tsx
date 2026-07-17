"use client";

/**
 * AURA — OAuth connections settings page.
 *
 * Lists each MCP provider (Spotify, Google Calendar, GitHub) and lets the
 * user connect/disconnect their account. Connection state is queried from
 * FastAPI's /api/oauth/status endpoint.
 *
 * When the user clicks "Connect":
 *   1. GET /api/oauth/{provider}/login  → returns { auth_url, state }
 *   2. Redirect to auth_url (provider's authorize endpoint)
 *   3. Provider redirects to either:
 *        - FastAPI /api/oauth/callback/{provider}  (Google Calendar)
 *        - NextAuth callback                        (Spotify/GitHub — then the
 *                                                     frontend separately calls
 *                                                     FastAPI to register the
 *                                                     token)
 *
 * For Spotify/GitHub, NextAuth handles the OAuth dance and stashes the access
 * token in the JWT. We then POST it to FastAPI for storage. (Simpler than
 * running two separate flows.)
 */
import { useEffect, useState, useCallback } from "react";
import { useSession } from "next-auth/react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Github, Music, Calendar, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { auraApi } from "@/lib/aura/api";

interface ProviderStatus {
  configured: boolean;
  connected: boolean;
}

const PROVIDER_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; color: string }
> = {
  spotify: { label: "Spotify", icon: Music, color: "text-green-500" },
  google: { label: "Google Calendar", icon: Calendar, color: "text-blue-500" },
  github: { label: "GitHub", icon: Github, color: "text-foreground" },
};

export default function SettingsPage() {
  const { data: session, status } = useSession();
  const [statuses, setStatuses] = useState<Record<string, ProviderStatus>>({});
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await auraApi.oauthStatus();
      setStatuses(r.providers);
    } catch (e: any) {
      toast.error("Failed to load OAuth status", { description: e.message });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const connect = useCallback(
    async (provider: string) => {
      setConnecting(provider);
      try {
        const r = await auraApi.oauthLogin(provider);
        if (r.auth_url) {
          window.location.href = r.auth_url;
        }
      } catch (e: any) {
        toast.error(`Failed to start ${provider} OAuth`, { description: e.message });
        setConnecting(null);
      }
    },
    []
  );

  const disconnect = useCallback(
    async (provider: string) => {
      try {
        await auraApi.oauthDisconnect(provider);
        toast.success(`${PROVIDER_META[provider]?.label || provider} disconnected`);
        refresh();
      } catch (e: any) {
        toast.error(`Failed to disconnect ${provider}`, { description: e.message });
      }
    },
    [refresh]
  );

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Connect external accounts so AURA's MCP tools can read your real data.
          </p>
        </div>

        <Card className="p-6 space-y-4 bg-card/60 backdrop-blur-sm">
          <div>
            <h2 className="text-sm font-semibold">Connected Accounts</h2>
            <p className="text-[11px] text-muted-foreground">
              Tokens are stored encrypted in PostgreSQL. AURA refreshes them automatically.
            </p>
          </div>

          <div className="space-y-3">
            {Object.entries(PROVIDER_META).map(([provider, meta]) => {
              const Icon = meta.icon;
              const s = statuses[provider] || { configured: false, connected: false };
              return (
                <div
                  key={provider}
                  className="flex items-center justify-between p-3 rounded-lg border border-border bg-background/40"
                >
                  <div className="flex items-center gap-3">
                    <Icon className={`w-5 h-5 ${meta.color}`} />
                    <div>
                      <div className="text-sm font-medium">{meta.label}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {s.configured
                          ? s.connected
                            ? "Connected — real data flowing"
                            : "Not connected"
                          : "Not configured (set OAuth creds in backend .env)"}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {s.connected ? (
                      <>
                        <Badge variant="outline" className="text-[10px] gap-1 text-green-500 border-green-500/30">
                          <CheckCircle2 className="w-3 h-3" /> Live
                        </Badge>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => disconnect(provider)}
                        >
                          Disconnect
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="default"
                        disabled={!s.configured || connecting === provider}
                        onClick={() => connect(provider)}
                      >
                        {connecting === provider ? (
                          <Loader2 className="w-3 h-3 animate-spin mr-1" />
                        ) : null}
                        Connect
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {loading && (
            <div className="text-[11px] text-muted-foreground flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Loading status…
            </div>
          )}
        </Card>

        <Card className="p-6 space-y-3 bg-card/60 backdrop-blur-sm">
          <div>
            <h2 className="text-sm font-semibold">Session</h2>
            <p className="text-[11px] text-muted-foreground">Current NextAuth session info</p>
          </div>
          <div className="text-[11px] font-mono space-y-1 text-muted-foreground">
            <div>user_id:  {(session as any)?.userId || "u_aura"}</div>
            <div>name:     {session?.user?.name || "—"}</div>
            <div>email:    {session?.user?.email || "—"}</div>
            <div>timezone: {(session as any)?.timezone || "UTC"}</div>
          </div>
        </Card>
      </div>
    </div>
  );
}
