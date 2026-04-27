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
from typing import Optional, List

SERVICE_NAME = os.getenv("SERVICE_NAME", "meta-builder")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8010"))
DB_NAME = os.getenv("DB_NAME", "tank")
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
CREATE TABLE IF NOT EXISTS service_registry (
    name TEXT PRIMARY KEY,
    port INTEGER NOT NULL,
    db_name TEXT,
    description TEXT,
    capabilities JSONB DEFAULT '[]',
    registered_at TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW()
);
"""

KNOWN_SERVICES = [
    {"name": "api-proxy", "port": 8001, "db_name": "tank", "description": "Market data proxy", "capabilities": ["market", "news", "sentiment", "price"]},
    {"name": "research", "port": 8002, "db_name": "research", "description": "Quant research and signals", "capabilities": ["signals", "analysis"]},
    {"name": "decision", "port": 8003, "db_name": "decision", "description": "Multi-agent decision engine", "capabilities": ["voting", "decisions"]},
    {"name": "executor", "port": 8004, "db_name": "executor", "description": "Order execution", "capabilities": ["orders", "execution"]},
    {"name": "ledger", "port": 8005, "db_name": "ledger", "description": "Immutable audit ledger", "capabilities": ["audit", "verification"]},
    {"name": "tournament", "port": 8006, "db_name": "tournament", "description": "Strategy tournaments", "capabilities": ["tournaments", "rankings"]},
    {"name": "monitor", "port": 8007, "db_name": "tank", "description": "Service health monitor", "capabilities": ["health", "status"]},
    {"name": "memory-sync", "port": 8008, "db_name": "memory", "description": "Distributed state sync", "capabilities": ["state", "sync"]},
    {"name": "banks-service", "port": 8009, "db_name": "banks", "description": "Deployment management", "capabilities": ["deployments", "rollback"]},
    {"name": "meta-builder", "port": 8010, "db_name": "tank", "description": "Service registry", "capabilities": ["registry", "discovery"]},
    {"name": "risk-manager", "port": 8011, "db_name": "tank", "description": "Risk checks and limits", "capabilities": ["risk", "limits"]},
    {"name": "portfolio-tracker", "port": 8012, "db_name": "ledger", "description": "Portfolio and positions", "capabilities": ["portfolio", "positions"]},
]

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
            cur.execute("SELECT COUNT(*) FROM service_registry")
            count = cur.fetchone()[0]
            if count == 0:
                for svc in KNOWN_SERVICES:
                    cur.execute(
                        """INSERT INTO service_registry (name, port, db_name, description, capabilities)
                           VALUES (%s,%s,%s,%s,%s::jsonb)
                           ON CONFLICT (name) DO NOTHING""",
                        (svc["name"], svc["port"], svc["db_name"],
                         svc["description"], json.dumps(svc["capabilities"])),
                    )
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


class ServiceIn(BaseModel):
    name: str
    port: int
    db: Optional[str] = None
    description: Optional[str] = None
    capabilities: Optional[List[str]] = []


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


@app.get("/services")
def list_services():
    REQ.labels("GET", "/services", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM service_registry ORDER BY name")
        rows = cur.fetchall()
    return {"services": [dict(r) for r in rows], "count": len(rows)}


@app.post("/services")
def register_service(body: ServiceIn):
    REQ.labels("POST", "/services", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO service_registry (name, port, db_name, description, capabilities, last_seen)
               VALUES (%s,%s,%s,%s,%s::jsonb, NOW())
               ON CONFLICT (name) DO UPDATE
               SET port=EXCLUDED.port, db_name=EXCLUDED.db_name,
                   description=EXCLUDED.description, capabilities=EXCLUDED.capabilities,
                   last_seen=NOW()""",
            (body.name, body.port, body.db, body.description, json.dumps(body.capabilities or [])),
        )
    db.commit()
    return {"ok": True, "name": body.name}


@app.get("/services/{name}")
def get_service(name: str):
    REQ.labels("GET", "/services/{name}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM service_registry WHERE name=%s", (name,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Service not found")
    return dict(row)


@app.delete("/services/{name}")
def delete_service(name: str):
    REQ.labels("DELETE", "/services/{name}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor() as cur:
        cur.execute("DELETE FROM service_registry WHERE name=%s RETURNING name", (name,))
        deleted = cur.fetchone()
    db.commit()
    if not deleted:
        raise HTTPException(404, "Service not found")
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
