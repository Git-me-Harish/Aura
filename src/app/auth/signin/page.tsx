"use client";

/**
 * AURA — Sign-in page.
 *
 * Primary: email + password (real accounts created via /auth/signup).
 * Optional: GitHub / Spotify OAuth (only shown if env-configured).
 */
import { useState } from "react";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Github, Music, Loader2, AlertCircle } from "lucide-react";
import { toast } from "sonner";
import Image from "next/image";

export default function SignInPage() {
  const router = useRouter();
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasGithub = !!process.env.NEXT_PUBLIC_GITHUB_ENABLED;
  const hasSpotify = !!process.env.NEXT_PUBLIC_SPOTIFY_ENABLED;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await signIn("credentials", {
        email,
        password,
        redirect: false,
        callbackUrl,
      });
      if (!res || res.error) {
        setError("Invalid email or password. Please try again.");
        setLoading(false);
        return;
      }
      toast.success("Welcome back to AURA!");
      router.push(callbackUrl);
      router.refresh();
    } catch (e: any) {
      setError(e?.message || "Sign-in failed. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-muted/30 p-4">
      <Card className="max-w-md w-full p-8 space-y-6 bg-card/80 backdrop-blur-md border-border/60">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-primary/10 text-primary mb-2">
            <Image src="/logo.png" alt="AURA" width={32} height={32} priority className="w-8 h-8 object-contain" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Welcome back</h1>
          <p className="text-sm text-muted-foreground">
            Sign in to your AURA account
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-xs">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="bg-background/60"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-xs">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="bg-background/60"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 text-xs text-destructive bg-destructive/10 border border-destructive/30 rounded-md p-2.5">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button
            type="submit"
            disabled={loading}
            className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
          >
            {loading && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            {loading ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <div className="text-center text-xs text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link href="/auth/signup" className="text-primary hover:underline font-medium">
            Create one
          </Link>
        </div>

        {(hasGithub || hasSpotify) && (
          <>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-border/60" />
              </div>
              <div className="relative flex justify-center text-[10px] uppercase tracking-wider text-muted-foreground">
                <span className="bg-card px-2">or continue with</span>
              </div>
            </div>
            <div className="space-y-2">
              {hasGithub && (
                <Button
                  variant="outline"
                  className="w-full justify-start gap-3"
                  onClick={() => signIn("github", { callbackUrl })}
                >
                  <Github className="w-4 h-4" /> Continue with GitHub
                </Button>
              )}
              {hasSpotify && (
                <Button
                  variant="outline"
                  className="w-full justify-start gap-3"
                  onClick={() => signIn("spotify", { callbackUrl })}
                >
                  <Music className="w-4 h-4" /> Continue with Spotify
                </Button>
              )}
            </div>
          </>
        )}

        <div className="text-[11px] text-muted-foreground text-center pt-2 border-t border-border/40">
          Multi-user auth via NextAuth.js · JWT validated by FastAPI
        </div>
      </Card>
    </div>
  );
}
