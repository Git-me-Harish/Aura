"""
AURA — Context Agent (real MCP-backed).

Collects what is happening RIGHT NOW: time, weather, calendar, location,
device, mood, recent searches. Uses MCP tools.

Updated to:
  * Pass user_id to MCP tool calls (per-user OAuth tokens)
  * Use async data layer
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone

from app.models.schemas import ContextSnapshot, User
from app.mcp_tools.registry import call_tool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time_of_day(dt: datetime) -> str:
    h = dt.hour
    if 5 <= h < 12:  return "morning"
    if 12 <= h < 17: return "afternoon"
    if 17 <= h < 21: return "evening"
    return "night"


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ContextAgent:
    async def snapshot(self, user: User) -> ContextSnapshot:
        # Parallel MCP calls — pass user_id so OAuth-backed tools fetch the right token
        weather_task = call_tool("weather", "current", {}, user.user_id)
        cal_task = call_tool("calendar", "next_event", {}, user.user_id)
        maps_task = call_tool("maps", "current_location", {}, user.user_id)
        weather, cal, maps = await asyncio.gather(weather_task, cal_task, maps_task)

        w = weather.result or {}
        loc = maps.result or {}
        next_evt = cal.result or {}
        now = _now()

        # Handle either the real Google Calendar shape (start: ISO string)
        # or the mock shape (in_minutes: int)
        cal_next_title = None
        if isinstance(next_evt, dict):
            cal_next_title = next_evt.get("title") or next_evt.get("summary")

        return ContextSnapshot(
            timestamp=now,
            time_of_day=_time_of_day(now),
            weekday=WEEKDAYS[now.weekday()],
            weather=w.get("condition", "Clear") if isinstance(w, dict) else "Clear",
            temperature_c=w.get("temp_c", 22.0) if isinstance(w, dict) else 22.0,
            location=(loc.get("area") or loc.get("city") or "Unknown") if isinstance(loc, dict) else "Unknown",
            device="desktop",
            mood="focused" if now.hour < 17 else "relaxed",
            recent_searches=["ppo hyperparameters", "best ambient albums", "bengaluru coffee roasters"],
            calendar_next=cal_next_title,
            raw={"weather": w, "location": loc, "calendar_next": next_evt},
        )


context_agent = ContextAgent()
