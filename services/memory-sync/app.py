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
from typing import Any

SERVICE_NAME = os.getenv("SERVICE_NAME", "memory-sync")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8008"))
DB_NAME = os.getenv("DB_NAME", "memory")
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
CREATE TABLE IF NOT EXISTS state (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (namespace, key)
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


class SyncIn(BaseModel):
    key: str
    value: Any
    namespace: str = "default"


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


@app.post("/sync")
def sync_state(body: SyncIn):
    REQ.labels("POST", "/sync", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    value_json = json.dumps(body.value)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO state (namespace, key, value, updated_at)
               VALUES (%s, %s, %s::jsonb, NOW())
               ON CONFLICT (namespace, key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = NOW()""",
            (body.namespace, body.key, value_json),
        )
    db.commit()
    return {"ok": True, "key": body.key, "namespace": body.namespace}


@app.get("/sync/{namespace}")
def get_namespace(namespace: str):
    REQ.labels("GET", "/sync/{namespace}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT key, value, updated_at FROM state WHERE namespace=%s ORDER BY updated_at DESC",
            (namespace,),
        )
        rows = cur.fetchall()
    return {
        "namespace": namespace,
        "items": [{"key": r["key"], "value": r["value"], "updated_at": str(r["updated_at"])} for r in rows],
    }


@app.get("/sync/{namespace}/{key}")
def get_state_key(namespace: str, key: str):
    REQ.labels("GET", "/sync/{namespace}/{key}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM state WHERE namespace=%s AND key=%s", (namespace, key))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Key not found")
    return {"namespace": row["namespace"], "key": row["key"], "value": row["value"],
            "updated_at": str(row["updated_at"])}


@app.delete("/sync/{namespace}/{key}")
def delete_state_key(namespace: str, key: str):
    REQ.labels("DELETE", "/sync/{namespace}/{key}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor() as cur:
        cur.execute("DELETE FROM state WHERE namespace=%s AND key=%s RETURNING key", (namespace, key))
        deleted = cur.fetchone()
    db.commit()
    if not deleted:
        raise HTTPException(404, "Key not found")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
