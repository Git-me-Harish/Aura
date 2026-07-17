"use client";

/**
 * AURA — Sign-up page.
 *
 * Creates a real user account (email + password, bcrypt-hashed) via the
 * /api/auth/signup route, then immediately signs the user in.
 */
import { useState } from "react";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import Image from "next/image";

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }

    setLoading(true);
    try {
      // Step 1: create the account
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data?.error || "Sign-up failed. Please try again.");
        setLoading(false);
        return;
      }

      // Step 2: sign in (sets the NextAuth session cookie)
      const signInRes = await signIn("credentials", {
        email,
        password,
        redirect: false,
        callbackUrl: "/",
      });
      if (!signInRes || signInRes.error) {
        // Account was created but auto-signin failed — fall back to /auth/signin
        toast.success("Account created! Please sign in.");
        router.push("/auth/signin");
        return;
      }

      toast.success("Welcome to AURA!", {
        description: "Your personalized recommendation engine is ready.",
      });
      router.push("/");
      router.refresh();
    } catch (e: any) {
      setError(e?.message || "Sign-up failed. Please try again.");
      setLoading(false);
    }
  }

  // Real-time password strength indicator
  const pwStrength = (() => {
    let s = 0;
    if (password.length >= 8) s++;
    if (password.length >= 12) s++;
    if (/[A-Z]/.test(password) && /[a-z]/.test(password)) s++;
    if (/\d/.test(password)) s++;
    if (/[^A-Za-z0-9]/.test(password)) s++;
    return s; // 0-5
  })();
  const strengthLabel = ["", "Weak", "Fair", "Good", "Strong", "Excellent"][pwStrength];
  const strengthColor = [
    "",
    "bg-destructive",
    "bg-amber-500",
    "bg-yellow-500",
    "bg-primary",
    "bg-primary",
  ][pwStrength];

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-background to-muted/30 p-4">
      <Card className="max-w-md w-full p-8 space-y-6 bg-card/80 backdrop-blur-md border-border/60">
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-primary/10 text-primary mb-2">
            <Image src="/logo.png" alt="AURA" width={32} height={32} priority className="w-8 h-8 object-contain" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Create your AURA account</h1>
          <p className="text-sm text-muted-foreground">
            Get personalized recommendations powered by 9 AI agents + RL
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name" className="text-xs">Name</Label>
            <Input
              id="name"
              type="text"
              autoComplete="name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              className="bg-background/60"
            />
          </div>
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
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              className="bg-background/60"
            />
            {password.length > 0 && (
              <div className="flex items-center gap-2 pt-1">
                <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all ${strengthColor}`}
                    style={{ width: `${(pwStrength / 5) * 100}%` }}
                  />
                </div>
                <span className="text-[10px] text-muted-foreground w-16 text-right">
                  {strengthLabel}
                </span>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm" className="text-xs">Confirm password</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-enter your password"
              className="bg-background/60"
            />
            {confirm.length > 0 && password === confirm && (
              <div className="flex items-center gap-1.5 text-[10px] text-primary pt-1">
                <CheckCircle2 className="w-3 h-3" /> Passwords match
              </div>
            )}
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
            {loading ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <div className="text-center text-xs text-muted-foreground">
          Already have an account?{" "}
          <Link href="/auth/signin" className="text-primary hover:underline font-medium">
            Sign in
          </Link>
        </div>

        <div className="text-[11px] text-muted-foreground text-center pt-2 border-t border-border/40">
          Each account gets its own preference profile, RL policy, and memory.
          <br />
          Your data is isolated — other users see different recommendations.
        </div>
      </Card>
    </div>
  );
}
