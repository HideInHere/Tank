import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "memory-sync")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8008"))
DB_NAME = os.getenv("DB_NAME", "memory")
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

class SyncRequest(BaseModel):
    namespace: str
    key: str
    value: str

class UpdateRequest(BaseModel):
    value: str

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

@app.post("/sync")
async def sync_state(req: SyncRequest):
    await redis_client.hset(f"memory:{req.namespace}", req.key, req.value)
    return {"synced": True, "key": req.key, "namespace": req.namespace}

@app.get("/state/{namespace}/{key}")
async def get_state(namespace: str, key: str):
    value = await redis_client.hget(f"memory:{namespace}", key)
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"namespace": namespace, "key": key, "value": value}

@app.put("/state/{namespace}/{key}")
async def update_state(namespace: str, key: str, req: UpdateRequest):
    await redis_client.hset(f"memory:{namespace}", key, req.value)
    return {"namespace": namespace, "key": key, "value": req.value, "updated": True}

@app.delete("/state/{namespace}/{key}")
async def delete_state(namespace: str, key: str):
    deleted = await redis_client.hdel(f"memory:{namespace}", key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"namespace": namespace, "key": key, "deleted": True}

@app.get("/namespaces")
async def list_namespaces():
    keys = await redis_client.keys("memory:*")
    return {"namespaces": [k.replace("memory:", "") for k in keys]}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
