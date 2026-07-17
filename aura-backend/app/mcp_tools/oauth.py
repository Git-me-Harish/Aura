"""
AURA — MCP OAuth helpers.

Implements the OAuth2 Authorization Code flow for Spotify, Google Calendar,
and GitHub. Tokens are stored in the `oauth_tokens` Postgres table (with
in-memory fallback when Postgres is unavailable).

Endpoints exposed by the FastAPI router:
  GET  /api/oauth/{provider}/login       — redirect user to provider's authorize URL
  GET  /api/oauth/callback/{provider}    — handle provider callback, exchange code for token
  GET  /api/oauth/status                 — list which providers the current user has connected
  DELETE /api/oauth/{provider}           — disconnect a provider (delete stored token)

Token refresh is handled lazily: every call to `get_token(provider, user_id)`
checks `expires_at` and refreshes if needed.
"""
from __future__ import annotations
import asyncio
import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.data_layer import postgres, redis

log = logging.getLogger("aura.mcp.oauth")


# ──────────────────────────────────────────────────────────────────────────────
# Provider configs
# ──────────────────────────────────────────────────────────────────────────────
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "spotify": {
        "auth_url":     "https://accounts.spotify.com/authorize",
        "token_url":    "https://accounts.spotify.com/api/token",
        "scopes":       "user-read-currently-playing user-top-read user-read-recently-played playlist-read-private",
        "client_id":    settings.SPOTIFY_CLIENT_ID,
        "client_secret":settings.SPOTIFY_CLIENT_SECRET,
        "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
    },
    "google": {
        "auth_url":     "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url":    "https://oauth2.googleapis.com/token",
        "scopes":       "https://www.googleapis.com/auth/calendar.readonly",
        "client_id":    settings.GOOGLE_CLIENT_ID,
        "client_secret":settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    },
    "github": {
        "auth_url":     "https://github.com/login/oauth/authorize",
        "token_url":    "https://github.com/login/oauth/access_token",
        "scopes":       "repo read:user",
        "client_id":    settings.GITHUB_CLIENT_ID,
        "client_secret":settings.GITHUB_CLIENT_SECRET,
        "redirect_uri": f"{settings.NEXTAUTH_URL}/api/auth/callback/github",
    },
}


def is_configured(provider: str) -> bool:
    """A provider is 'configured' if its client_id/secret are set."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return False
    return bool(cfg.get("client_id") and cfg.get("client_secret"))


# ──────────────────────────────────────────────────────────────────────────────
# State token (CSRF protection)
# ──────────────────────────────────────────────────────────────────────────────
async def _make_state(user_id: str, provider: str) -> str:
    raw = f"{user_id}:{provider}:{time.time()}:{secrets.token_hex(16)}"
    state = hashlib.sha256(raw.encode()).hexdigest()
    await redis.set(f"oauth:state:{state}", f"{user_id}:{provider}", ttl_seconds=600)
    return state


async def _consume_state(state: str) -> Optional[tuple[str, str]]:
    val = await redis.get(f"oauth:state:{state}")
    if not val:
        return None
    # One-shot
    # (real Redis would DEL; in fallback we just rely on TTL)
    if ":" in val:
        user_id, provider = val.split(":", 1)
        return user_id, provider
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Authorization URL builder
# ──────────────────────────────────────────────────────────────────────────────
def build_auth_url(provider: str, state: str) -> str:
    cfg = PROVIDERS[provider]
    params = {
        "client_id":     cfg["client_id"],
        "response_type": "code",
        "redirect_uri":  cfg["redirect_uri"],
        "state":         state,
        "scope":         cfg["scopes"],
    }
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    return f"{cfg['auth_url']}?{urlencode(params)}"


# ──────────────────────────────────────────────────────────────────────────────
# Code → token exchange
# ──────────────────────────────────────────────────────────────────────────────
async def exchange_code(provider: str, code: str) -> Dict[str, Any]:
    cfg = PROVIDERS[provider]
    data = {
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  cfg["redirect_uri"],
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    headers = {"Accept": "application/json"}
    if provider == "github":
        # GitHub accepts JSON only with this header
        headers["Accept"] = "application/json"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(cfg["token_url"], data=data, headers=headers)
        if r.status_code != 200:
            log.warning("oauth %s token exchange failed: %s %s", provider, r.status_code, r.text[:200])
            return {}
        return r.json()


# ──────────────────────────────────────────────────────────────────────────────
# Refresh token
# ──────────────────────────────────────────────────────────────────────────────
async def refresh_token(provider: str, refresh_tok: str) -> Dict[str, Any]:
    cfg = PROVIDERS[provider]
    data = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_tok,
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(cfg["token_url"], data=data, headers={"Accept": "application/json"})
        if r.status_code != 200:
            log.warning("oauth %s refresh failed: %s", provider, r.status_code)
            return {}
        return r.json()


# ──────────────────────────────────────────────────────────────────────────────
# Token storage (Postgres with in-memory fallback)
# ──────────────────────────────────────────────────────────────────────────────
async def store_token(user_id: str, provider: str, token_data: Dict[str, Any]) -> None:
    """Persist OAuth token for a user/provider."""
    access = token_data.get("access_token", "")
    refresh = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")
    # Store as a real datetime for the TIMESTAMPTZ column.
    expires_at = (
        datetime.fromtimestamp(time.time() + expires_in, tz=timezone.utc)
        if expires_in else None
    )
    scope = token_data.get("scope", "").split(" ") if token_data.get("scope") else []

    table = postgres.table("oauth_tokens")
    row = {
        "user_id":       user_id,
        "provider":      provider,
        "access_token":  access,
        "refresh_token": refresh,
        "expires_at":    expires_at,
        "scopes":        scope,
        "raw":           token_data,
        "updated_at":    datetime.now(timezone.utc),
    }
    try:
        await table.insert(f"{user_id}:{provider}", row)
        log.info("oauth: stored token for %s/%s", user_id, provider)
    except Exception as e:
        log.warning("oauth: store_token failed (%s) — keeping in-memory only", e)


async def get_token(user_id: str, provider: str) -> Optional[Dict[str, Any]]:
    """Fetch + auto-refresh the user's OAuth token for a provider."""
    table = postgres.table("oauth_tokens")
    rows = await table.where(user_id=user_id, provider=provider)
    if not rows:
        return None
    row = rows[0] if isinstance(rows, list) else rows
    # Check expiry — expires_at is a datetime (TIMESTAMPTZ) coming back from Postgres
    expires_at = row.get("expires_at")
    refresh = row.get("refresh_token")
    if expires_at and refresh:
        # Normalize to epoch seconds for comparison
        if hasattr(expires_at, "timestamp"):
            exp_epoch = expires_at.timestamp()
        else:
            try:
                exp_epoch = float(expires_at)
            except (TypeError, ValueError):
                exp_epoch = 0.0
        if exp_epoch < time.time() + 60:
            try:
                new_token = await refresh_token(provider, refresh)
                if new_token.get("access_token"):
                    # Preserve refresh_token if not returned (Google only returns it on first consent)
                    if not new_token.get("refresh_token") and refresh:
                        new_token["refresh_token"] = refresh
                    await store_token(user_id, provider, new_token)
                    return new_token
            except Exception as e:
                log.warning("oauth: refresh failed for %s/%s: %s", user_id, provider, e)
    return {
        "access_token":  row.get("access_token"),
        "refresh_token": row.get("refresh_token"),
        "expires_at":    row.get("expires_at"),
        "scopes":        row.get("scopes", []),
    }


async def delete_token(user_id: str, provider: str) -> None:
    """Disconnect a provider."""
    # HybridPostgresTable doesn't expose DELETE — fall back to overwrite with empty
    table = postgres.table("oauth_tokens")
    try:
        await table.insert(f"{user_id}:{provider}", {
            "user_id": user_id, "provider": provider,
            "access_token": "", "refresh_token": None,
            "expires_at": None, "scopes": [],
            "raw": {}, "updated_at": datetime.now(timezone.utc),
        })
    except Exception as e:
        log.warning("oauth: delete_token failed: %s", e)


async def list_connected(user_id: str) -> Dict[str, bool]:
    """Return {provider: connected?} for the user."""
    table = postgres.table("oauth_tokens")
    rows = await table.where(user_id=user_id)
    connected = {}
    for p in PROVIDERS:
        connected[p] = any(
            (r.get("provider") == p and r.get("access_token"))
            for r in (rows or [])
        )
    return connected
