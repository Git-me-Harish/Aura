/**
 * AURA — Sign-up API route.
 *
 * Creates a new user with email + password (bcrypt-hashed) in the Auth DB.
 * After signup, the frontend calls signIn("credentials", ...) which establishes
 * the NextAuth session via the credentials provider's authorize() callback.
 *
 * Returns:
 *   200 { ok: true, user: {...} }   — account created
 *   400 { error: "..." }            — validation error
 *   409 { error: "exists" }         — email already registered
 *   500 { error: "..." }            — unexpected
 */
import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { db } from "@/lib/db";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const email = String(body.email || "").trim().toLowerCase();
    const password = String(body.password || "");
    const name = String(body.name || "").trim();

    // ── Validate ────────────────────────────────────────────────────────
    if (!EMAIL_RE.test(email)) {
      return NextResponse.json(
        { error: "Please enter a valid email address." },
        { status: 400 }
      );
    }
    if (password.length < 8) {
      return NextResponse.json(
        { error: "Password must be at least 8 characters long." },
        { status: 400 }
      );
    }
    if (password.length > 200) {
      return NextResponse.json({ error: "Password is too long." }, { status: 400 });
    }
    if (!name || name.length < 2) {
      return NextResponse.json(
        { error: "Please enter your name (at least 2 characters)." },
        { status: 400 }
      );
    }

    // ── Check for existing user ─────────────────────────────────────────
    const existing = await db.user.findUnique({ where: { email } });
    if (existing) {
      return NextResponse.json(
        { error: "An account with this email already exists. Try signing in instead." },
        { status: 409 }
      );
    }

    // ── Hash password + create user ─────────────────────────────────────
    const passwordHash = await bcrypt.hash(password, 10);
    const user = await db.user.create({
      data: {
        email,
        name,
        passwordHash,
        timezone: "Asia/Calcutta",
        preferredLanguage: "en",
      },
    });

    return NextResponse.json({
      ok: true,
      user: { id: user.id, email: user.email, name: user.name },
    });
  } catch (e: any) {
    console.error("[signup] error:", e);
    return NextResponse.json(
      { error: e?.message || "Sign-up failed. Please try again." },
      { status: 500 }
    );
  }
}

export async function GET() {
  return NextResponse.json({ error: "Method not allowed" }, { status: 405 });
}
