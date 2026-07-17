"""Smoke-test the streaming WebSocket.

Connects to /api/ws, kicks off an orchestration, and prints every event
received for 10 seconds. Verifies that agent_start / agent_step /
orchestration_complete events are emitted in real time.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request

import websockets


async def main():
    uri = "ws://127.0.0.1:8000/api/ws"
    print(f"connecting to {uri} …")
    async with websockets.connect(uri) as ws:
        # Read hello
        hello = await asyncio.wait_for(ws.recv(), timeout=3.0)
        print(f"  ← hello: {json.loads(hello)['type']}")

        # Kick off orchestration
        print("POST /api/orchestrate …")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/orchestrate",
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
        request_id = resp.get("request_id", "?")
        print(f"  → started: request_id={request_id}")

        # Receive events for up to 15s
        events = []
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                evt = json.loads(msg)
                t = evt.get("type")
                if t == "tick":
                    continue  # ignore liveness
                events.append(evt)
                if t == "agent_start":
                    print(f"  ← agent_start:  {evt.get('agent'):14}  req={evt.get('request_id')}")
                elif t == "agent_step":
                    print(f"  ← agent_step:   {evt.get('agent'):14}  {evt.get('duration_ms')}ms  {evt.get('output_summary','')[:50]}")
                elif t == "orchestration_complete":
                    print(f"  ← orchestration_complete  req={evt.get('request_id')}")
                    break
                elif t == "rl_update":
                    print(f"  ← rl_update:    policy={evt.get('rl',{}).get('policy_version')}")
                else:
                    print(f"  ← {t}")
            except asyncio.TimeoutError:
                continue

    print(f"\ntotal events received: {len(events)}")
    starts = [e for e in events if e.get("type") == "agent_start"]
    steps = [e for e in events if e.get("type") == "agent_step"]
    completes = [e for e in events if e.get("type") == "orchestration_complete"]
    print(f"  agent_start:         {len(starts)}")
    print(f"  agent_step:          {len(steps)}")
    print(f"  orchestration_complete: {len(completes)}")


if __name__ == "__main__":
    asyncio.run(main())
