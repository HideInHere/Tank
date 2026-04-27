import os
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "ledger")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8005"))
DB_NAME = os.getenv("DB_NAME", "ledger")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])

redis_client = None
db_conn = None

GENESIS_HASH = hashlib.sha256(b"genesis").hexdigest()
chain: list = [{"id": 0, "event_type": "genesis", "data": "chain_init", "source": "system", "timestamp": "2026-01-01T00:00:00Z", "hash": GENESIS_HASH, "prev_hash": "0" * 64}]

class EntryRequest(BaseModel):
    event_type: str
    data: str
    source: str

def compute_hash(prev_hash: str, event_type: str, data: str, timestamp: str) -> str:
    content = f"{prev_hash}{event_type}{data}{timestamp}"
    return hashlib.sha256(content.encode()).hexdigest()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, db_conn
    redis_client = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
        encoding="utf-8", decode_responses=True
    )
    try:
        db_conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=DB_NAME, user=POSTGRES_USER, password=POSTGRES_PASSWORD
        )
        log.info("db_connected", service=SERVICE_NAME, db=DB_NAME)
    except Exception as e:
        log.warning("db_connect_failed", error=str(e))
    log.info("service_started", service=SERVICE_NAME, port=SERVICE_PORT)
    yield
    if redis_client:
        await redis_client.aclose()
    if db_conn:
        db_conn.close()

app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "db": db_conn is not None and not db_conn.closed, "redis": redis_client is not None}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/entries")
async def add_entry(req: EntryRequest):
    prev = chain[-1]
    ts = datetime.now(timezone.utc).isoformat()
    new_hash = compute_hash(prev["hash"], req.event_type, req.data, ts)
    entry = {"id": len(chain), "event_type": req.event_type, "data": req.data, "source": req.source, "timestamp": ts, "hash": new_hash, "prev_hash": prev["hash"]}
    chain.append(entry)
    return entry

@app.get("/entries")
async def list_entries():
    return chain[-100:]

@app.get("/entries/{entry_id}")
async def get_entry(entry_id: int):
    if entry_id < 0 or entry_id >= len(chain):
        raise HTTPException(status_code=404, detail="Entry not found")
    return chain[entry_id]

@app.get("/verify")
async def verify_chain():
    valid = True
    for i in range(1, len(chain)):
        entry = chain[i]
        expected = compute_hash(chain[i - 1]["hash"], entry["event_type"], entry["data"], entry["timestamp"])
        if expected != entry["hash"]:
            valid = False
            break
    return {"valid": valid, "length": len(chain), "last_hash": chain[-1]["hash"]}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
