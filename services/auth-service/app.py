import os, time, logging, secrets, hashlib, base64, json
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "auth-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8022"))
DB_NAME = os.getenv("DB_NAME", "tank")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")
START_TIME = time.time()
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
db = None
r = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    permissions JSONB DEFAULT '["read"]',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    last_used TIMESTAMP
);
"""

@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def connect_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                            password=PG_PASS, dbname=DB_NAME, connect_timeout=5)

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
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS,
                            decode_responses=True, socket_connect_timeout=3)
        r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis error: %s", e)
    yield
    if db and not db.closed:
        db.close()

app = FastAPI(title=SERVICE_NAME, version="1.0.0", lifespan=lifespan)

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def make_token() -> str:
    payload = {"ts": int(time.time()), "service": "tank"}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    sig = hashlib.sha256(f"{encoded}{JWT_SECRET}".encode()).hexdigest()[:16]
    return f"{encoded}.{sig}"

@app.get("/health")
def health():
    db_ok = bool(db and not db.closed)
    try:
        r_ok = bool(r and r.ping())
    except Exception:
        r_ok = False
    return {"status": "healthy", "service": SERVICE_NAME, "db": db_ok, "redis": r_ok,
            "uptime": round(time.time() - START_TIME)}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/keys")
def create_key(body: dict):
    REQ.labels("POST", "/keys", "200").inc()
    if "name" not in body:
        raise HTTPException(400, "Missing field: name")
    name = body["name"]
    permissions = body.get("permissions", ["read"])
    raw_key = secrets.token_hex(32)
    key_hash = hash_key(raw_key)
    if not db or db.closed:
        return {"name": name, "key": raw_key, "id": None, "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO api_keys(name,key_hash,permissions) VALUES(%s,%s,%s) RETURNING id",
                (name, key_hash, json.dumps(permissions)))
            key_id = cur.fetchone()["id"]
        db.commit()
        return {"name": name, "key": raw_key, "id": key_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/keys")
def list_keys():
    REQ.labels("GET", "/keys", "200").inc()
    if not db or db.closed:
        return {"keys": [], "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id,name,key_hash,permissions,active,created_at,last_used "
                        "FROM api_keys ORDER BY created_at DESC")
            rows = []
            for row in cur.fetchall():
                d = dict(row)
                d["key_hash"] = d["key_hash"][:8] + "..."
                rows.append(d)
        return {"keys": rows}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.delete("/keys/{key_id}")
def delete_key(key_id: str):
    REQ.labels("DELETE", "/keys/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE api_keys SET active=FALSE WHERE id=%s", (key_id,))
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.post("/validate")
def validate_key(body: dict):
    REQ.labels("POST", "/validate", "200").inc()
    if "key" not in body:
        raise HTTPException(400, "Missing field: key")
    key_hash = hash_key(body["key"])
    if not db or db.closed:
        return {"valid": False, "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id,name,permissions FROM api_keys WHERE key_hash=%s AND active=TRUE",
                (key_hash,))
            row = cur.fetchone()
        if not row:
            return {"valid": False}
        if db and not db.closed:
            try:
                with db.cursor() as cur:
                    cur.execute("UPDATE api_keys SET last_used=NOW() WHERE id=%s", (row["id"],))
                db.commit()
            except Exception:
                db.rollback()
        return {"valid": True, "name": row["name"], "permissions": row["permissions"]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/token")
def get_token():
    REQ.labels("GET", "/token", "200").inc()
    return {"token": make_token(), "expires_in": 3600}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
