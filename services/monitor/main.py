import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import httpx
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "monitor")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8007"))
DB_NAME = os.getenv("DB_NAME", "tank")
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

SERVICE_URLS = {
    "api-proxy": "http://api-proxy:8001",
    "research": "http://research:8002",
    "decision": "http://decision:8003",
    "executor": "http://executor:8004",
    "ledger": "http://ledger:8005",
    "tournament": "http://tournament:8006",
    "monitor": "http://monitor:8007",
    "memory-sync": "http://memory-sync:8008",
    "risk": "http://risk:8009",
    "portfolio": "http://portfolio:8010",
    "analytics": "http://analytics:8011",
    "notifier": "http://notifier:8012",
    "scheduler": "http://scheduler:8013",
    "data-ingest": "http://data-ingest:8014",
    "backtester": "http://backtester:8015",
    "optimizer": "http://optimizer:8016",
    "correlation": "http://correlation:8017",
    "model-server": "http://model-server:8018",
    "feature-store": "http://feature-store:8019",
    "rebalancer": "http://rebalancer:8020",
    "compliance": "http://compliance:8021",
    "reporting": "http://reporting:8022",
    "webhook": "http://webhook:8023",
    "gateway": "http://gateway:8000",
}

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

async def check_service(name: str, url: str, client: httpx.AsyncClient) -> dict:
    try:
        resp = await client.get(f"{url}/health", timeout=2.0)
        return {"status": "ok" if resp.status_code == 200 else "degraded", "code": resp.status_code}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}

@app.get("/status")
async def system_status():
    async with httpx.AsyncClient() as client:
        tasks = [check_service(name, url, client) for name, url in SERVICE_URLS.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return {name: (results[i] if not isinstance(results[i], Exception) else {"status": "error", "error": str(results[i])}) for i, name in enumerate(SERVICE_URLS)}

@app.get("/alerts")
async def get_alerts():
    return [
        {"id": "a-001", "severity": "warning", "service": "data-ingest", "message": "Feed latency above threshold: 450ms", "triggered_at": "2026-04-27T09:45:00Z"},
        {"id": "a-002", "severity": "info",    "service": "executor",    "message": "Paper trading mode active",            "triggered_at": "2026-04-27T08:00:00Z"},
        {"id": "a-003", "severity": "critical", "service": "model-server","message": "GPU memory utilization at 94%",        "triggered_at": "2026-04-27T10:12:00Z"},
    ]

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
