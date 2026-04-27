import os, time, logging, json, hashlib
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

SERVICE_NAME = os.getenv("SERVICE_NAME", "ledger")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8005"))
DB_NAME = os.getenv("DB_NAME", "ledger")
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
CREATE TABLE IF NOT EXISTS audit_log (
    hash TEXT PRIMARY KEY,
    prev_hash TEXT,
    action TEXT NOT NULL,
    actor TEXT,
    details JSONB DEFAULT '{}',
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


class AuditIn(BaseModel):
    action: str
    actor: Optional[str] = None
    details: Optional[dict] = {}


def compute_hash(prev_hash: str, action: str, actor: str, details: dict, ts: str) -> str:
    actor = actor or ""
    raw = f"{prev_hash}{action}{actor}{json.dumps(details, sort_keys=True)}{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()


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


@app.post("/audit", status_code=201)
def create_audit(body: AuditIn):
    REQ.labels("POST", "/audit", "201").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT hash FROM audit_log ORDER BY created_at DESC LIMIT 1")
        prev = cur.fetchone()
    prev_hash = prev["hash"] if prev else "0" * 64
    ts = str(int(time.time()))
    entry_hash = compute_hash(prev_hash, body.action, body.actor or "", body.details or {}, ts)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (hash, prev_hash, action, actor, details) VALUES (%s,%s,%s,%s,%s::jsonb)",
            (entry_hash, prev_hash, body.action, body.actor, json.dumps(body.details or {})),
        )
    db.commit()
    return {"hash": entry_hash, "ok": True}


@app.get("/audit")
def list_audit(limit: int = 100):
    REQ.labels("GET", "/audit", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    return {"entries": [dict(r) for r in rows], "count": len(rows)}


@app.get("/audit/{entry_hash}")
def get_audit(entry_hash: str):
    REQ.labels("GET", "/audit/{hash}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM audit_log WHERE hash = %s", (entry_hash,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Entry not found")
    return dict(row)


@app.get("/verify/{entry_hash}")
def verify_chain(entry_hash: str):
    REQ.labels("GET", "/verify/{hash}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM audit_log ORDER BY created_at ASC")
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {"valid": True, "chain_length": 0}
    target_found = False
    for row in rows:
        if row["hash"] == entry_hash:
            target_found = True
            break
    if not target_found:
        raise HTTPException(404, "Hash not found in chain")
    prev_hash = "0" * 64
    for i, row in enumerate(rows):
        if row["prev_hash"] != prev_hash:
            return {"valid": False, "chain_length": i}
        prev_hash = row["hash"]
        if row["hash"] == entry_hash:
            return {"valid": True, "chain_length": i + 1}
    return {"valid": False, "chain_length": len(rows)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
