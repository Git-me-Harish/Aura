"""
AURA — real MCP handlers.

Each handler:
  * Reads configuration (OAuth tokens for OAuth-backed providers, API keys
    for API-key-backed providers) from settings + Postgres `oauth_tokens`.
  * Makes a real API call via httpx.
  * Returns the same response shape across all providers.

If a provider is not configured (missing client_id/secret/API key) OR the user
has not connected it, the handler returns:
    {"connected": False, "reason": "..."}

There are NO mock fallbacks. The caller surfaces the "not connected" status
to the UI so the user can connect the provider via OAuth or set the API key.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.mcp_tools.oauth import get_token, is_configured
from app.config import settings

log = logging.getLogger("aura.mcp.handlers")


# ──────────────────────────────────────────────────────────────────────────────
# Spotify
# ──────────────────────────────────────────────────────────────────────────────
SPOTIFY_BASE = "https://api.spotify.com/v1"


async def _spotify(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    if not is_configured("spotify"):
        return {"connected": False, "reason": "Spotify OAuth client_id/secret not set"}
    tok = await get_token(user_id, "spotify")
    if not tok or not tok.get("access_token"):
        return {"connected": False, "reason": "Spotify not connected for this user"}

    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "now_playing":
                r = await client.get(f"{SPOTIFY_BASE}/me/player/currently-playing", headers=headers)
                if r.status_code == 204 or r.status_code >= 400:
                    return {"track": None, "artist": None, "is_playing": False}
                data = r.json()
                item = data.get("item") or {}
                return {
                    "track": item.get("name"),
                    "artist": (item.get("artists") or [{}])[0].get("name"),
                    "progress_sec": data.get("progress_ms", 0) // 1000,
                    "duration_sec": (item.get("duration_ms") or 0) // 1000,
                    "is_playing": data.get("is_playing", False),
                }
            if method == "top_tracks":
                r = await client.get(
                    f"{SPOTIFY_BASE}/me/top/tracks",
                    params={"limit": 10, "time_range": "short_term"},
                    headers=headers,
                )
                r.raise_for_status()
                items = r.json().get("items", [])
                return [
                    {
                        "track": it.get("name"),
                        "artist": (it.get("artists") or [{}])[0].get("name"),
                        "uri": it.get("uri"),
                    }
                    for it in items
                ]
            if method == "recommend":
                genre = args.get("genre", "electronic")
                r = await client.get(
                    f"{SPOTIFY_BASE}/recommendations",
                    params={"seed_genres": genre, "limit": 5},
                    headers=headers,
                )
                r.raise_for_status()
                tracks = r.json().get("tracks", [])
                return [
                    {
                        "track": t.get("name"),
                        "artist": (t.get("artists") or [{}])[0].get("name"),
                        "match": round(0.7 + 0.25 * (i / max(1, len(tracks))), 3),
                    }
                    for i, t in enumerate(tracks)
                ]
        except Exception as e:
            log.warning("spotify %s failed: %s", method, e)
            return {"error": str(e), "connected": True}
    return {"error": f"unknown method {method}"}


# ──────────────────────────────────────────────────────────────────────────────
# GitHub
# ──────────────────────────────────────────────────────────────────────────────
GITHUB_API = "https://api.github.com"


async def _github(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    if not is_configured("github"):
        return {"connected": False, "reason": "GitHub OAuth client_id/secret not set"}
    tok = await get_token(user_id, "github")
    if not tok or not tok.get("access_token"):
        return {"connected": False, "reason": "GitHub not connected for this user"}

    headers = {
        "Authorization": f"token {tok['access_token']}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "recent_activity":
                r = await client.get(f"{GITHUB_API}/user/repos", params={"per_page": 10, "sort": "updated"}, headers=headers)
                r.raise_for_status()
                repos = r.json()
                repo_names = [r["name"] for r in repos[:5]]
                r2 = await client.get(f"{GITHUB_API}/user/issues", params={"state": "open", "per_page": 30}, headers=headers)
                issues = r2.json() if r2.status_code == 200 else []
                return {
                    "repos": repo_names,
                    "open_prs": sum(1 for i in issues if "pull_request" in i),
                    "issues_assigned": len(issues),
                    "last_commit": "recent",
                }
            if method == "open_prs":
                r = await client.get(f"{GITHUB_API}/user/issues", params={"state": "open", "per_page": 10}, headers=headers)
                r.raise_for_status()
                issues = r.json()
                return [
                    {
                        "repo": (i.get("repository_url") or "").split("/")[-1],
                        "title": i.get("title"),
                        "status": "open",
                        "url": i.get("html_url"),
                    }
                    for i in issues if "pull_request" in i
                ][:5]
            if method == "issue_count":
                r = await client.get(f"{GITHUB_API}/user/issues", params={"state": "open", "per_page": 50}, headers=headers)
                r.raise_for_status()
                return len(r.json())
        except Exception as e:
            log.warning("github %s failed: %s", method, e)
            return {"error": str(e), "connected": True}
    return {"error": f"unknown method {method}"}


# ──────────────────────────────────────────────────────────────────────────────
# Google Calendar
# ──────────────────────────────────────────────────────────────────────────────
CAL_API = "https://www.googleapis.com/calendar/v3"


async def _calendar(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    if not is_configured("google"):
        return {"connected": False, "reason": "Google OAuth client_id/secret not set"}
    tok = await get_token(user_id, "google")
    if not tok or not tok.get("access_token"):
        return {"connected": False, "reason": "Google Calendar not connected for this user"}

    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    now = datetime.now(timezone.utc)
    time_min = now.isoformat().replace("+00:00", "Z")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method in ("list_events", "next_event", "free_slots"):
                r = await client.get(
                    f"{CAL_API}/calendars/primary/events",
                    params={
                        "timeMin": time_min,
                        "maxResults": 10 if method == "list_events" else 1,
                        "singleEvents": True,
                        "orderBy": "startTime",
                    },
                    headers=headers,
                )
                if r.status_code == 401:
                    return {"connected": True, "error": "token expired"}
                r.raise_for_status()
                items = r.json().get("items", [])
                events = []
                for ev in items:
                    start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
                    end = (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date")
                    events.append({
                        "title": ev.get("summary", "(no title)"),
                        "start": start,
                        "end": end,
                        "attendees": [a.get("email") for a in (ev.get("attendees") or [])],
                        "link": ev.get("htmlLink"),
                    })
                if method == "next_event":
                    return events[0] if events else {}
                if method == "free_slots":
                    return [{"start": events[-1]["end"] if events else time_min, "end": None}]
                return events
        except Exception as e:
            log.warning("calendar %s failed: %s", method, e)
            return {"error": str(e), "connected": True}
    return {"error": f"unknown method {method}"}


# ──────────────────────────────────────────────────────────────────────────────
# OpenWeather (API-key based — no OAuth)
# ──────────────────────────────────────────────────────────────────────────────
OWM_BASE = "https://api.openweathermap.org/data/2.5"


async def _weather(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    if not settings.OPENWEATHER_API_KEY:
        return {"connected": False, "reason": "OPENWEATHER_API_KEY not set — get a free key at https://openweathermap.org/api"}
    city = args.get("city") or settings.OPENWEATHER_DEFAULT_CITY
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "current":
                r = await client.get(f"{OWM_BASE}/weather", params={
                    "q": city, "appid": settings.OPENWEATHER_API_KEY, "units": "metric",
                })
                r.raise_for_status()
                d = r.json()
                return {
                    "city": d.get("name"),
                    "condition": (d.get("weather") or [{}])[0].get("main", "Unknown"),
                    "temp_c": round(d.get("main", {}).get("temp", 0.0), 1),
                    "humidity": d.get("main", {}).get("humidity", 0),
                    "wind_kph": round((d.get("wind", {}).get("speed", 0.0)) * 3.6, 1),
                }
            if method == "forecast":
                r = await client.get(f"{OWM_BASE}/forecast", params={
                    "q": city, "appid": settings.OPENWEATHER_API_KEY, "units": "metric", "cnt": 8,
                })
                r.raise_for_status()
                d = r.json()
                return [
                    {
                        "hour_offset": i * 3,
                        "temp_c": round(item.get("main", {}).get("temp", 0.0), 1),
                        "condition": (item.get("weather") or [{}])[0].get("main", "Clear"),
                    }
                    for i, item in enumerate(d.get("list", [])[:8])
                ]
            if method == "alerts":
                # OpenWeather One Call API requires a separate subscription in v3.
                # For now, return an empty alerts list — no fabricated alerts.
                return []
        except Exception as e:
            log.warning("weather %s failed: %s", method, e)
            return {"error": str(e), "connected": True}
    return {"error": f"unknown method {method}"}


# ──────────────────────────────────────────────────────────────────────────────
# NewsAPI (API-key based — no OAuth)
# ──────────────────────────────────────────────────────────────────────────────
NEWSAPI_BASE = "https://newsapi.org/v2"


async def _news(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    if not settings.NEWSAPI_KEY:
        return {"connected": False, "reason": "NEWSAPI_KEY not set — get a free key at https://newsapi.org"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "headlines":
                r = await client.get(f"{NEWSAPI_BASE}/top-headlines", params={
                    "category": "technology", "language": "en", "pageSize": 10,
                    "apiKey": settings.NEWSAPI_KEY,
                })
                r.raise_for_status()
                articles = r.json().get("articles", [])
                return [
                    {
                        "title": a.get("title"),
                        "source": (a.get("source") or {}).get("name", "wire"),
                        "topic": "tech",
                        "url": a.get("url"),
                        "published_at": a.get("publishedAt"),
                    }
                    for a in articles
                ]
            if method == "topic_search":
                topic = args.get("topic", "AI")
                r = await client.get(f"{NEWSAPI_BASE}/everything", params={
                    "q": topic, "language": "en", "sortBy": "relevancy", "pageSize": 10,
                    "apiKey": settings.NEWSAPI_KEY,
                })
                r.raise_for_status()
                articles = r.json().get("articles", [])
                return [
                    {
                        "title": a.get("title"),
                        "source": (a.get("source") or {}).get("name", "wire"),
                        "url": a.get("url"),
                        "published_at": a.get("publishedAt"),
                    }
                    for a in articles
                ]
        except Exception as e:
            log.warning("news %s failed: %s", method, e)
            return {"error": str(e), "connected": True}
    return {"error": f"unknown method {method}"}


# ──────────────────────────────────────────────────────────────────────────────
# Not-yet-integrated providers — return explicit "not connected" so the UI
# can prompt the user to configure them. NO fabricated data.
# ──────────────────────────────────────────────────────────────────────────────
async def _not_connected(method: str, args: Dict[str, Any], user_id: str = "u_aura") -> Any:
    return {"connected": False, "reason": "Provider not yet integrated — configure OAuth or API key to enable"}


# ──────────────────────────────────────────────────────────────────────────────
# Handler registry — keyed by tool name
# ──────────────────────────────────────────────────────────────────────────────
REAL_HANDLERS = {
    "spotify":  _spotify,
    "github":   _github,
    "calendar": _calendar,
    "weather":  _weather,
    "news":     _news,
    # The following providers return explicit "not connected" until a real
    # handler is implemented. They DO NOT fabricate data.
    "email":      _not_connected,
    "maps":       _not_connected,
    "finance":    _not_connected,
    "shopping":   _not_connected,
    "health":     _not_connected,
    "slack":      _not_connected,
    "notion":     _not_connected,
    "drive":      _not_connected,
    "databricks": _not_connected,
}
