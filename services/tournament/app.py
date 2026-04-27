import os, time, logging, json
from contextlib import asynccontextmanager
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

SERVICE_NAME = os.getenv("SERVICE_NAME", "tournament")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8006"))
DB_NAME = os.getenv("DB_NAME", "tournament")
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
CREATE TABLE IF NOT EXISTS tournaments (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    start_date DATE,
    end_date DATE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS tournament_results (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tournament_id TEXT REFERENCES tournaments(id),
    strategy TEXT NOT NULL,
    pnl FLOAT,
    sharpe FLOAT,
    metadata JSONB DEFAULT '{}',
    submitted_at TIMESTAMP DEFAULT NOW()
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


class TournamentIn(BaseModel):
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SubmitIn(BaseModel):
    strategy: str
    pnl: Optional[float] = None
    sharpe: Optional[float] = None
    metadata: Optional[dict] = {}


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


@app.get("/tournaments")
def list_tournaments():
    REQ.labels("GET", "/tournaments", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM tournaments ORDER BY created_at DESC")
        rows = cur.fetchall()
    return {"tournaments": [dict(r) for r in rows], "count": len(rows)}


@app.post("/tournaments", status_code=201)
def create_tournament(body: TournamentIn):
    REQ.labels("POST", "/tournaments", "201").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO tournaments (name, start_date, end_date) VALUES (%s,%s,%s) RETURNING *",
            (body.name, body.start_date, body.end_date),
        )
        row = dict(cur.fetchone())
    db.commit()
    return row


@app.get("/tournaments/{tournament_id}/results")
def get_results(tournament_id: str):
    REQ.labels("GET", "/tournaments/{id}/results", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM tournament_results WHERE tournament_id=%s ORDER BY pnl DESC NULLS LAST",
            (tournament_id,),
        )
        rows = cur.fetchall()
    return {"tournament_id": tournament_id, "results": [dict(r) for r in rows]}


@app.post("/tournaments/{tournament_id}/submit")
def submit_result(tournament_id: str, body: SubmitIn):
    REQ.labels("POST", "/tournaments/{id}/submit", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor() as cur:
        cur.execute("SELECT id FROM tournaments WHERE id=%s", (tournament_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Tournament not found")
        cur.execute(
            """INSERT INTO tournament_results (tournament_id, strategy, pnl, sharpe, metadata)
               VALUES (%s,%s,%s,%s,%s::jsonb)""",
            (tournament_id, body.strategy, body.pnl, body.sharpe, json.dumps(body.metadata or {})),
        )
    db.commit()
    return {"ok": True, "tournament_id": tournament_id, "strategy": body.strategy}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
