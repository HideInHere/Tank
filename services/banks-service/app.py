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

SERVICE_NAME = os.getenv("SERVICE_NAME", "banks-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8009"))
DB_NAME = os.getenv("DB_NAME", "banks")
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
CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    strategy TEXT DEFAULT 'rolling',
    status TEXT DEFAULT 'pending',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
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


class DeploymentIn(BaseModel):
    service: str
    version: str
    strategy: str = "rolling"


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


@app.get("/deployments")
def list_deployments():
    REQ.labels("GET", "/deployments", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM deployments ORDER BY created_at DESC")
        rows = cur.fetchall()
    return {"deployments": [dict(r) for r in rows], "count": len(rows)}


@app.post("/deployments", status_code=201)
def create_deployment(body: DeploymentIn):
    REQ.labels("POST", "/deployments", "201").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO deployments (service_name, version, strategy)
               VALUES (%s, %s, %s) RETURNING *""",
            (body.service, body.version, body.strategy),
        )
        row = dict(cur.fetchone())
    db.commit()
    return row


@app.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: str):
    REQ.labels("GET", "/deployments/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM deployments WHERE id=%s", (deployment_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Deployment not found")
    return dict(row)


@app.post("/deployments/{deployment_id}/rollback")
def rollback_deployment(deployment_id: str):
    REQ.labels("POST", "/deployments/{id}/rollback", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "UPDATE deployments SET status='rolling_back', updated_at=NOW() WHERE id=%s RETURNING *",
            (deployment_id,),
        )
        row = cur.fetchone()
    db.commit()
    if not row:
        raise HTTPException(404, "Deployment not found")
    return {"ok": True, "deployment": dict(row)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
