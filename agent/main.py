"""Tank Agent — persistent AI trading agent for the openclaw gateway."""

import asyncio
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

import anthropic
import httpx
import psycopg2
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
OPENCLAW_URL = os.getenv("OPENCLAW_URL", "http://openclaw-gateway:18789")
OPENCLAW_SECRET = os.getenv("OPENCLAW_SECRET", "")
TANK_AGENT_ID = os.getenv("TANK_AGENT_ID", "tank-agent-001")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

SERVICE_PORT = int(os.getenv("SERVICE_PORT", "9000"))

# Service → port map for slash-command routing
SERVICE_PORTS: dict[str, int] = {
    "api-proxy": 8001,
    "research": 8002,
    "decision": 8003,
    "executor": 8004,
    "ledger": 8005,
    "tournament": 8006,
    "monitor": 8007,
    "memory-sync": 8008,
    "banks-service": 8009,
    "meta-builder": 8010,
    "risk-manager": 8011,
    "portfolio-tracker": 8012,
    "market-data": 8013,
    "signal-generator": 8014,
    "order-router": 8015,
    "position-manager": 8016,
    "alert-service": 8017,
    "report-generator": 8018,
    "backtest-runner": 8019,
    "strategy-optimizer": 8020,
    "feed-aggregator": 8021,
    "auth-service": 8022,
    "notification-service": 8023,
    "analytics-service": 8024,
}

TRADE_KEYWORDS = {"buy", "sell", "long", "short", "trade", "order", "position", "signal"}

SYSTEM_PROMPT = (
    "You are Tank, an AI trading assistant. You analyze markets, coordinate with "
    "microservices, and make data-driven trading decisions. Be concise. When you see "
    "/service/method commands, explain what you're routing."
)

MAX_HISTORY = 50

log = structlog.get_logger()
START_TIME = time.time()

# ── Prometheus metrics ────────────────────────────────────────────────────────

messages_total = Counter("messages_total", "Total messages processed", ["session"])
message_duration = Histogram("message_duration_seconds", "Message processing latency")
active_sessions = Gauge("active_sessions", "Number of active sessions")
claude_api_calls = Counter("claude_api_calls_total", "Total Claude API calls")

# ── Runtime state ─────────────────────────────────────────────────────────────

sessions: dict[str, list[dict]] = defaultdict(list)
recent_decisions: list[dict] = []
redis_client: aioredis.Redis | None = None
claude_client: anthropic.AsyncAnthropic | None = None
db_conn: psycopg2.extensions.connection | None = None


# ── Database ──────────────────────────────────────────────────────────────────

def _init_db() -> "psycopg2.extensions.connection | None":
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname="tank",
            connect_timeout=5,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    last_seen TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS trade_decisions (
                    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                    session_id TEXT,
                    symbol TEXT,
                    action TEXT,
                    confidence FLOAT,
                    reasoning TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute(
                """
                INSERT INTO agents (id, name, status)
                VALUES (%s, %s, 'active')
                ON CONFLICT (id) DO UPDATE SET last_seen = NOW(), status = 'active'
                """,
                (TANK_AGENT_ID, "tank"),
            )
        log.info("database_ready")
        return conn
    except Exception as exc:
        log.warning("database_unavailable", error=str(exc))
        return None


def _persist_message(session_id: str, role: str, content: str) -> None:
    if db_conn is None:
        return
    try:
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, role, content),
            )
    except Exception as exc:
        log.warning("db_persist_failed", error=str(exc))


# ── Redis ─────────────────────────────────────────────────────────────────────

async def _init_redis() -> "aioredis.Redis | None":
    try:
        client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        await client.ping()
        log.info("redis_ready")
        return client
    except Exception as exc:
        log.warning("redis_unavailable", error=str(exc))
        return None


async def _publish_decision(session_id: str, response_text: str) -> None:
    if redis_client is None:
        return
    lower = response_text.lower()
    if not any(kw in lower for kw in TRADE_KEYWORDS):
        return
    try:
        await redis_client.xadd(
            "tank:decisions",
            {"session_id": session_id, "content": response_text[:500]},
        )
    except Exception as exc:
        log.warning("redis_publish_failed", error=str(exc))


# ── OpenClaw registration ─────────────────────────────────────────────────────

async def _register_with_openclaw() -> None:
    await asyncio.sleep(5)
    payload = {
        "id": TANK_AGENT_ID,
        "name": "tank",
        "url": "http://tank-agent:9000",
        "capabilities": ["trading", "research", "execution"],
    }
    headers = {"Authorization": f"Bearer {OPENCLAW_SECRET}"} if OPENCLAW_SECRET else {}
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{OPENCLAW_URL}/agents/register", json=payload, headers=headers
                )
                resp.raise_for_status()
                log.info("openclaw_registered", status=resp.status_code)
                return
        except Exception as exc:
            log.warning("openclaw_registration_failed", error=str(exc))
            await asyncio.sleep(30)


# ── Slash-command routing ─────────────────────────────────────────────────────

async def _route_slash_command(content: str) -> str | None:
    """Route /service/path commands to the appropriate microservice."""
    if not content.startswith("/"):
        return None
    stripped = content.lstrip("/")
    parts = stripped.split("/", 1)
    service = parts[0]
    path = "/" + parts[1] if len(parts) > 1 else "/"
    port = SERVICE_PORTS.get(service)
    if port is None:
        return f"[router] Unknown service '{service}'. Available: {', '.join(SERVICE_PORTS)}"
    url = f"http://{service}:{port}{path}"
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(url)
            return f"[router -> {service}:{port}{path}] {resp.status_code}: {resp.text[:400]}"
    except Exception as exc:
        return f"[router -> {service}:{port}{path}] error: {exc}"


# ── AI core ───────────────────────────────────────────────────────────────────

async def _call_claude(session_id: str, user_content: str) -> tuple[str, int]:
    """Append to history, call Claude, return (reply_text, tokens_used)."""
    history = sessions[session_id]

    # Inject upstream service response as context when content is a slash command
    service_ctx: str | None = None
    if user_content.startswith("/"):
        service_ctx = await _route_slash_command(user_content)

    augmented = user_content
    if service_ctx:
        augmented = f"{user_content}\n\n[Service response]: {service_ctx}"

    history.append({"role": "user", "content": augmented})
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    claude_api_calls.inc()
    resp = await claude_client.messages.create(  # type: ignore[union-attr]
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=history,
    )
    reply = resp.content[0].text
    tokens = resp.usage.input_tokens + resp.usage.output_tokens

    history.append({"role": "assistant", "content": reply})
    return reply, tokens


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, claude_client, db_conn

    db_conn = _init_db()
    redis_client = await _init_redis()
    claude_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    reg_task = asyncio.create_task(_register_with_openclaw())

    yield

    reg_task.cancel()
    try:
        await reg_task
    except asyncio.CancelledError:
        pass

    if redis_client:
        await redis_client.aclose()
    if db_conn:
        db_conn.close()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Tank Agent", version="1.0.0", lifespan=lifespan)


# ── Request models ────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    content: str
    from_id: str = "user"
    session_id: str = "default"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent_id": TANK_AGENT_ID,
        "sessions_active": len(sessions),
        "uptime": round(time.time() - START_TIME, 1),
        "claude_ready": claude_client is not None,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    active_sessions.set(len(sessions))
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/message")
async def message(req: MessageRequest) -> dict[str, Any]:
    t0 = time.time()
    messages_total.labels(session=req.session_id).inc()
    active_sessions.set(len(sessions))

    if claude_client is None:
        raise HTTPException(status_code=503, detail="Claude client not initialised")

    try:
        _persist_message(req.session_id, "user", req.content)
        reply, tokens = await _call_claude(req.session_id, req.content)
        _persist_message(req.session_id, "assistant", reply)
        await _publish_decision(req.session_id, reply)

        if any(kw in reply.lower() for kw in TRADE_KEYWORDS):
            decision = {
                "session_id": req.session_id,
                "reasoning": reply[:300],
                "ts": time.time(),
            }
            recent_decisions.append(decision)
            if len(recent_decisions) > 20:
                recent_decisions.pop(0)

        message_duration.observe(time.time() - t0)
        return {"response": reply, "session_id": req.session_id, "tokens_used": tokens}
    except anthropic.APIError as exc:
        log.error("claude_api_error", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Claude API error: {exc}") from exc
    except Exception as exc:
        log.error("message_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/sessions")
async def list_sessions() -> dict[str, Any]:
    return {
        "sessions": [
            {"session_id": sid, "message_count": len(msgs)}
            for sid, msgs in sessions.items()
        ]
    }


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    sessions.pop(session_id, None)
    active_sessions.set(len(sessions))
    return {"status": "cleared", "session_id": session_id}


@app.get("/status")
async def status() -> dict[str, Any]:
    return {
        "agent_id": TANK_AGENT_ID,
        "model": CLAUDE_MODEL,
        "uptime": round(time.time() - START_TIME, 1),
        "sessions_active": len(sessions),
        "redis_connected": redis_client is not None,
        "db_connected": db_conn is not None,
        "openclaw_url": OPENCLAW_URL,
        "recent_decisions": recent_decisions[-5:],
    }
