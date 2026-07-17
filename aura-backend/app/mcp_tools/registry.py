"""
AURA MCP Tool Layer — real-only, no mocks.

Every tool dispatches to its real handler in `app.mcp_tools.handlers.REAL_HANDLERS`.
If a provider is not configured (missing OAuth creds / API key) OR the user has
not connected it, the handler returns:
    {"connected": False, "reason": "..."}

The caller surfaces this status to the UI. There is NO fallback to fake data.

Every handler takes `(method, args, user_id)` so it can fetch the right OAuth
token per user.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models.schemas import MCPTool, MCPToolCall
from app.data_layer import redis, clickhouse
from app.config import settings
from app.mcp_tools.handlers import REAL_HANDLERS
from app.mcp_tools.oauth import PROVIDERS

log = logging.getLogger("aura.mcp.registry")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry (capabilities + connection status)
# ──────────────────────────────────────────────────────────────────────────────
TOOLS: Dict[str, MCPTool] = {
    "calendar": MCPTool(
        name="calendar", category="calendar",
        connected=bool(settings.GOOGLE_CLIENT_ID),
        description="Read upcoming events from user's Google Calendar",
        capabilities=["list_events", "next_event", "free_slots"],
    ),
    "email": MCPTool(
        name="email", category="email", connected=False,
        description="Summarize inbox and detect urgent threads (Gmail OAuth — coming soon)",
        capabilities=["inbox_summary", "unread_count", "send"],
    ),
    "github": MCPTool(
        name="github", category="github",
        connected=bool(settings.GITHUB_CLIENT_ID),
        description="Repo activity, PRs, issues for the user",
        capabilities=["recent_activity", "open_prs", "issue_count"],
    ),
    "spotify": MCPTool(
        name="spotify", category="spotify",
        connected=bool(settings.SPOTIFY_CLIENT_ID),
        description="Now-playing, top tracks, recommendations",
        capabilities=["now_playing", "top_tracks", "recommend"],
    ),
    "maps": MCPTool(
        name="maps", category="maps", connected=False,
        description="Location, commute time, nearby places (Google Maps API — coming soon)",
        capabilities=["current_location", "commute", "nearby"],
    ),
    "weather": MCPTool(
        name="weather", category="weather",
        connected=bool(settings.OPENWEATHER_API_KEY),
        description="Current conditions + 24h forecast via OpenWeather API",
        capabilities=["current", "forecast", "alerts"],
    ),
    "news": MCPTool(
        name="news", category="news",
        connected=bool(settings.NEWSAPI_KEY),
        description="Top headlines + topic search via NewsAPI",
        capabilities=["headlines", "topic_search"],
    ),
    "finance": MCPTool(
        name="finance", category="finance", connected=False,
        description="Portfolio snapshot and market movers (Alpha Vantage — coming soon)",
        capabilities=["portfolio", "movers", "ticker"],
    ),
    "shopping": MCPTool(
        name="shopping", category="shopping", connected=False,
        description="Cart, wishlist, price drops (Shopify / Amazon — coming soon)",
        capabilities=["cart", "wishlist", "deals"],
    ),
    "health": MCPTool(
        name="health", category="health", connected=False,
        description="Steps, sleep, heart rate trends (Apple Health / Strava — coming soon)",
        capabilities=["steps", "sleep", "heart_rate"],
    ),
    "slack": MCPTool(
        name="slack", category="slack", connected=False,
        description="Unread channels and DMs (Slack OAuth — coming soon)",
        capabilities=["unread", "mentions"],
    ),
    "notion": MCPTool(
        name="notion", category="notion", connected=False,
        description="Recent pages and tasks (Notion OAuth — coming soon)",
        capabilities=["recent_pages", "tasks"],
    ),
    "drive": MCPTool(
        name="drive", category="drive", connected=False,
        description="Recently modified docs (Google Drive OAuth — coming soon)",
        capabilities=["recent_files", "search"],
    ),
    "databricks": MCPTool(
        name="databricks", category="databricks", connected=False,
        description="Run SQL on the lakehouse (Databricks SQL — coming soon)",
        capabilities=["run_sql", "list_tables"],
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
async def call_tool(
    tool: str,
    method: str,
    args: Dict[str, Any] | None = None,
    user_id: str = "u_aura",
) -> MCPToolCall:
    """Invoke an MCP tool via its real handler.

    No mock fallback. If the tool isn't configured, the handler returns
    `{"connected": False, "reason": ...}` and the caller surfaces that to
    the UI.
    """
    args = args or {}
    t0 = _now()

    handler = REAL_HANDLERS.get(tool) if settings.USE_REAL_MCP else None
    if handler is None:
        result: Any = {"error": f"unknown tool {tool}"}
        success = False
    else:
        try:
            result = await handler(method, args, user_id)
            success = not (isinstance(result, dict) and result.get("error"))
        except Exception as e:
            log.warning("handler %s.%s crashed: %s", tool, method, e)
            result = {"error": str(e), "connected": False}
            success = False

    duration_ms = int((_now() - t0).total_seconds() * 1000)
    call = MCPToolCall(
        tool=tool, method=method, args=args,
        result=result, duration_ms=duration_ms,
    )
    # Cache the last call result for the dashboard
    await redis.set(f"mcp:last:{tool}", call.model_dump(mode="json"), ttl_seconds=600)

    # Persist to ClickHouse for audit + latency analytics (fire-and-forget)
    import asyncio
    asyncio.create_task(clickhouse.insert_one("mcp_calls", {
        "user_id": user_id,
        "tool": tool,
        "method": method,
        "args_json": str(args),
        "duration_ms": duration_ms,
        "success": 1 if success else 0,
        "ts": t0.isoformat(),
    }))

    return call


def list_tools() -> List[MCPTool]:
    return list(TOOLS.values())
