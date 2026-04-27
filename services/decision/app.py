import os, time, logging, json
from contextlib import asynccontextmanager
from collections import Counter as PyCounter
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed
from pydantic import BaseModel
from typing import Optional

SERVICE_NAME = os.getenv("SERVICE_NAME", "decision")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8003"))
DB_NAME = os.getenv("DB_NAME", "decision")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
START_TIME = time.time()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])

INIT_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence FLOAT,
    votes JSONB DEFAULT '[]',
    reasoning TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

db = None
r = None


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def connect_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASS, dbname=DB_NAME, connect_timeout=5,
    )


@asynccontextmanager
async def lifespan(app):
    global db, r
    try:
        db = connect_db()
        with db.cursor() as cur:
            cur.execute(INIT_SQL)
        db.commit()
        logger.info("DB connected: %s", DB_NAME)
    except Exception as e:
        logger.warning("DB error: %s", e)
    try:
        r = redis_lib.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS,
            decode_responses=True, socket_connect_timeout=3,
        )
        r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis error: %s", e)
    yield
    if db and not db.closed:
        db.close()


app = FastAPI(title=SERVICE_NAME, version="1.0.0", lifespan=lifespan)


class VoteIn(BaseModel):
    symbol: str
    action: str
    confidence: float = 0.5
    strategy: Optional[str] = None


class DecideIn(BaseModel):
    symbol: str


@app.get("/health")
def health():
    db_ok = bool(db and not db.closed)
    try:
        r_ok = bool(r and r.ping())
    except Exception:
        r_ok = False
    return {
        "status": "healthy", "service": SERVICE_NAME,
        "db": db_ok, "redis": r_ok,
        "uptime": round(time.time() - START_TIME),
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/vote")
def cast_vote(body: VoteIn):
    REQ.labels("POST", "/vote", "200").inc()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    vote = json.dumps({"action": body.action, "confidence": body.confidence, "strategy": body.strategy})
    r.rpush(f"votes:{body.symbol}", vote)
    r.expire(f"votes:{body.symbol}", 3600)
    return {"ok": True, "symbol": body.symbol, "action": body.action}


@app.get("/decisions")
def list_decisions(limit: int = 20):
    REQ.labels("GET", "/decisions", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM decisions ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    return {"decisions": [dict(row) for row in rows], "count": len(rows)}


@app.post("/decide")
def decide(body: DecideIn):
    REQ.labels("POST", "/decide", "200").inc()
    if not r:
        raise HTTPException(503, "Redis unavailable")
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    raw_votes = r.lrange(f"votes:{body.symbol}", 0, -1)
    votes = [json.loads(v) for v in raw_votes]
    if not votes:
        raise HTTPException(400, "No votes available for symbol")
    actions = [v["action"] for v in votes]
    tally = PyCounter(actions)
    winning_action = tally.most_common(1)[0][0]
    avg_confidence = round(
        sum(v["confidence"] for v in votes if v["action"] == winning_action) /
        max(1, tally[winning_action]), 4
    )
    votes_json = json.dumps(votes)
    reasoning = f"Majority vote: {winning_action} ({tally[winning_action]}/{len(votes)} votes)"
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO decisions (symbol, action, confidence, votes, reasoning)
               VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING *""",
            (body.symbol, winning_action, avg_confidence, votes_json, reasoning),
        )
        row = dict(cur.fetchone())
    db.commit()
    r.delete(f"votes:{body.symbol}")
    return row


@app.get("/decisions/{decision_id}")
def get_decision(decision_id: str):
    REQ.labels("GET", "/decisions/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM decisions WHERE id = %s", (decision_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Decision not found")
    return dict(row)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
