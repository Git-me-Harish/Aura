/**
 * AURA — NextAuth.js configuration.
 *
 * Providers:
 *   - Credentials (email + password)   ← primary, backed by Prisma + bcrypt
 *   - GitHub OAuth                     ← optional, when GITHUB_CLIENT_ID set
 *   - Spotify OAuth                    ← optional, when SPOTIFY_CLIENT_ID set
 *
 * Session strategy: JWT
 *   - The JWT is signed with NEXTAUTH_SECRET (must match the FastAPI env).
 *   - The frontend sends this JWT as `Authorization: Bearer <jwt>` to FastAPI,
 *     which validates it with python-jose.
 *
 * JWT bridge to FastAPI:
 *   - We override the default NextAuth JWT encoding to produce a SIGNED (not
 *     JWE-encrypted) HS256 token. FastAPI then validates it with the same
 *     secret. This avoids the JWE complexity that python-jose doesn't handle
 *     out of the box.
 *   - Implementation: we hook jwt.encode via the `encode` option.
 *
 * Callbacks:
 *   - jwt()    — embed user_id, name, timezone, preferred_language in the token
 *   - session() — expose those fields on the session object for the frontend
 */
import NextAuth, { type NextAuthOptions } from "next-auth";
import GithubProvider from "next-auth/providers/github";
import SpotifyProvider from "next-auth/providers/spotify";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { sign } from "jsonwebtoken";
import { db } from "@/lib/db";

const GITHUB_CLIENT_ID = process.env.GITHUB_CLIENT_ID || "";
const GITHUB_CLIENT_SECRET = process.env.GITHUB_CLIENT_SECRET || "";
const SPOTIFY_CLIENT_ID = process.env.SPOTIFY_CLIENT_ID || "";
const SPOTIFY_CLIENT_SECRET = process.env.SPOTIFY_CLIENT_SECRET || "";
const NEXTAUTH_SECRET = process.env.NEXTAUTH_SECRET || "aura-dev-secret-change-me-in-prod-32chars-min";

export const authOptions: NextAuthOptions = {
  providers: [
    // Primary: email + password (real account creation via /api/auth/signup)
    CredentialsProvider({
      id: "credentials",
      name: "AURA Account",
      credentials: {
        email:   { label: "Email",    type: "email",    placeholder: "you@example.com" },
        password:{ label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const email = String(credentials?.email || "").trim().toLowerCase();
        const password = String(credentials?.password || "");
        if (!email || !password) return null;

        const user = await db.user.findUnique({ where: { email } });
        if (!user || !user.passwordHash) return null;

        const ok = await bcrypt.compare(password, user.passwordHash);
        if (!ok) return null;

        return {
          id: user.id,
          name: user.name || user.email,
          email: user.email,
        };
      },
    }),

    // Optional OAuth providers
    ...(GITHUB_CLIENT_ID
      ? [
          GithubProvider({
            clientId: GITHUB_CLIENT_ID,
            clientSecret: GITHUB_CLIENT_SECRET,
            authorization: { params: { scope: "read:user repo user:email" } },
          }),
        ]
      : []),
    ...(SPOTIFY_CLIENT_ID
      ? [
          SpotifyProvider({
            clientId: SPOTIFY_CLIENT_ID,
            clientSecret: SPOTIFY_CLIENT_SECRET,
            authorization: {
              params: {
                scope:
                  "user-read-currently-playing user-top-read user-read-recently-played playlist-read-private",
              },
            },
          }),
        ]
      : []),
  ],
  session: { strategy: "jwt" },
  secret: NEXTAUTH_SECRET,

  callbacks: {
    async jwt({ token, user, account }) {
      // First sign-in: stash the user identity in the JWT
      if (user) {
        // Fetch the full user record to get timezone + preferred_language
        // (for OAuth providers, user.id is the provider's user id; we need
        // to find or create the local User record first).
        let dbUser = null;
        if (account?.provider === "credentials") {
          dbUser = await db.user.findUnique({ where: { id: user.id } });
        } else if (account?.provider) {
          // OAuth: find by email, or create a stub User
          dbUser = await db.user.findUnique({
            where: { email: user.email || "" },
          });
          if (!dbUser) {
            dbUser = await db.user.create({
              data: {
                email: user.email || `${account.provider}-${user.id}@aura.local`,
                name: user.name || "OAuth User",
                timezone: "Asia/Calcutta",
                preferredLanguage: "en",
              },
            });
          }
          // Link the OAuth account
          await db.account.upsert({
            where: {
              provider_providerAccountId: {
                provider: account.provider,
                providerAccountId: account.providerAccountId,
              },
            },
            update: {},
            create: {
              userId: dbUser.id,
              provider: account.provider,
              providerAccountId: account.providerAccountId,
              access_token: account.access_token || null,
              refresh_token: account.refresh_token || null,
              expires_at: account.expires_at || null,
              token_type: account.token_type || null,
              scope: account.scope || null,
              id_token: account.id_token || null,
            },
          });
        }

        token.user_id = dbUser?.id || (user.id as string);
        token.name = dbUser?.name || user.name || token.name;
        token.email = dbUser?.email || user.email;
        token.timezone = dbUser?.timezone || "Asia/Calcutta";
        token.preferred_language = dbUser?.preferredLanguage || "en";
      }
      // Stash OAuth access tokens so the frontend can forward them to FastAPI
      if (account?.access_token && account.provider !== "credentials") {
        token[`access_token_${account.provider}`] = account.access_token;
      }
      return token;
    },
    async session({ session, token }) {
      // Expose the JWT fields on the session object
      (session as any).userId = token.user_id || token.sub;
      (session as any).accessToken = sign(
        {
          sub: token.sub || token.user_id,
          name: token.name,
          email: token.email,
          user_id: token.user_id || token.sub,
          timezone: token.timezone || "Asia/Calcutta",
          preferred_language: token.preferred_language || "en",
          iat: Math.floor(Date.now() / 1000),
          exp: Math.floor(Date.now() / 1000) + 30 * 24 * 3600,
        },
        NEXTAUTH_SECRET,
        { algorithm: "HS256" }
      );
      (session as any).timezone = token.timezone;
      (session as any).preferred_language = token.preferred_language;
      return session;
    },
  },
  pages: {
    signIn: "/auth/signin",
  },
};

const handler = NextAuth(authOptions);
export { handler as GET, handler as POST };
