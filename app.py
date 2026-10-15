"""
Travel Planner — public web backend for a Claude Managed Agent.

Browser  --POST /api/chat-->  this server  --Managed Agents API-->  your agent
         <---- SSE stream ---               <---- session events ----

Your ANTHROPIC_API_KEY stays on the server; visitors never see it.
"""

import json
import os
import time
from collections import defaultdict, deque

from anthropic import APIStatusError, AsyncAnthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------------------------------------------------------- config
AGENT_ID = os.environ.get("AGENT_ID", "")
ENVIRONMENT_ID = os.environ.get("ENVIRONMENT_ID", "")
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")  # optional: require a code to use the app
MAX_MESSAGES_PER_HOUR = int(os.environ.get("MAX_MESSAGES_PER_HOUR", "5"))  # per visitor IP
# Hard spend cap per conversation (USD). The session stops when it reaches this.
SESSION_BUDGET_USD = float(os.environ.get("SESSION_BUDGET_USD", "3"))
MAX_MESSAGE_CHARS = 2000
TURN_TIMEOUT_SECONDS = 600

# Only these tools are auto-approved if the agent pauses to ask for permission.
SAFE_TOOLS = {"web_search", "web_fetch"}

client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from the environment
app = FastAPI(title="Travel Planner")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _rate_limited(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= MAX_MESSAGES_PER_HOUR:
        return True
    q.append(now)
    return False


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = None
    access_code: str | None = None


# ---------------------------------------------------------------- routes
@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/config")
async def config():
    return {"access_code_required": bool(ACCESS_CODE)}


@app.get("/healthz")
async def healthz():
    return {"ok": bool(AGENT_ID and ENVIRONMENT_ID and os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request):
    if not (AGENT_ID and ENVIRONMENT_ID):
        raise HTTPException(500, "Server is missing AGENT_ID or ENVIRONMENT_ID.")
    if ACCESS_CODE and body.access_code != ACCESS_CODE:
        raise HTTPException(401, "Wrong or missing access code.")
    if _rate_limited(_client_ip(request)):
        raise HTTPException(429, f"Limit of {MAX_MESSAGES_PER_HOUR} messages per hour reached. Try again later.")

    return StreamingResponse(
        _run_turn(body.message, body.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _run_turn(message: str, session_id: str | None):
    try:
        if not session_id:
            session = await client.beta.sessions.create(
                agent=AGENT_ID,
                environment_id=ENVIRONMENT_ID,
                title=message[:60],
                budget={
                    "type": "limit",
                    "max_list_cost": {"amount": str(round(SESSION_BUDGET_USD * 100)), "currency": "USD"},
                },
            )
            session_id = session.id
        yield _sse("session", {"session_id": session_id})

        tool_names: dict[str, str] = {}
        started = time.time()

        # Open the stream first, then send the message (as in Anthropic's quickstart).
        async with await client.beta.sessions.events.stream(session_id) as stream:
            await client.beta.sessions.events.send(
                session_id,
                events=[{"type": "user.message", "content": [{"type": "text", "text": message}]}],
            )

            async for event in stream:
                if time.time() - started > TURN_TIMEOUT_SECONDS:
                    yield _sse("error", {"message": "The agent took too long. Please try again."})
                    break

                etype = getattr(event, "type", "")

                if etype == "agent.message":
                    text = "".join(b.text for b in event.content if getattr(b, "type", "") == "text")
                    if text:
                        yield _sse("text", {"text": text})

                elif etype in ("agent.tool_use", "agent.mcp_tool_use"):
                    tool_names[event.id] = event.name
                    yield _sse("status", {"text": _describe_tool(event.name, getattr(event, "input", {}) or {})})

                elif etype == "session.status_idle":
                    stop = getattr(event, "stop_reason", None)
                    stop_type = getattr(stop, "type", "end_turn")
                    if stop_type == "requires_action":
                        confirmations = [
                            {
                                "type": "user.tool_confirmation",
                                "tool_use_id": eid,
                                "result": "allow" if tool_names.get(eid) in SAFE_TOOLS else "deny",
                            }
                            for eid in (getattr(stop, "event_ids", None) or [])
                        ]
                        if confirmations:
                            await client.beta.sessions.events.send(session_id, events=confirmations)
                            continue
                    if stop_type == "budget_reached":
                        yield _sse("error", {"message": "This conversation hit its spending limit. Start a new trip."})
                    break

                elif etype == "session.error":
                    err = getattr(event, "error", None)
                    yield _sse("error", {"message": getattr(err, "message", None) or "The agent hit an error."})
                    break

        yield _sse("done", {"session_id": session_id})

    except APIStatusError as exc:
        print(f"[chat error] {exc.status_code}: {exc}", flush=True)
        reason = getattr(exc, "message", "") or str(exc)
        yield _sse("error", {"message": f"The agent service returned an error ({exc.status_code}): {reason[:300]}"})
    except Exception as exc:  # surface a friendly message; details go to server logs
        print(f"[chat error] {type(exc).__name__}: {exc}", flush=True)
        yield _sse("error", {"message": f"Something went wrong talking to the agent ({type(exc).__name__}). Please try again."})


def _describe_tool(name: str, tool_input: dict) -> str:
    if name == "web_search" and tool_input.get("query"):
        return f"Searching: {tool_input['query']}"
    if name == "web_fetch" and tool_input.get("url"):
        return f"Reading: {tool_input['url']}"
    return f"Using {name}…"
