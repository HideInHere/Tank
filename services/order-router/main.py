import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "order-router")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8015"))
DB_NAME = os.getenv("DB_NAME", "executor")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None

VENUES: dict[str, float] = {"binance": 1.2, "coinbase": 1.8, "kraken": 2.1, "paper": 0.1}
routes: list[dict] = []


class RouteRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: Optional[float] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, db_conn
    redis_client = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
        encoding="utf-8", decode_responses=True
    )
    try:
        db_conn = psycopg2.connect(host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=DB_NAME, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
    except Exception as e:
        log.warning("db_connect_failed", error=str(e))
    log.info("service_started", service=SERVICE_NAME)
    yield
    if redis_client:
        await redis_client.aclose()
    if db_conn:
        db_conn.close()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME,
            "db": db_conn is not None and not db_conn.closed,
            "redis": redis_client is not None}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/route")
async def route_order(req: RouteRequest):
    best_venue = min(VENUES, key=lambda v: VENUES[v])
    route = {
        "route_id": str(uuid.uuid4()),
        "venue": best_venue,
        "estimated_latency_ms": VENUES[best_venue],
        "symbol": req.symbol,
        "side": req.side,
        "quantity": req.quantity,
        "price": req.price,
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }
    routes.insert(0, route)
    if len(routes) > 20:
        routes.pop()
    return route


@app.get("/venues")
async def list_venues():
    return {v: {"latency_ms": lat, "status": "active"} for v, lat in VENUES.items()}


@app.get("/latency")
async def get_latency():
    result = {v: lat for v, lat in VENUES.items()}
    result["measured_at"] = datetime.now(timezone.utc).isoformat()
    return result


@app.get("/routes")
async def list_routes():
    return routes[:20]


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
