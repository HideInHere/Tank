import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "feed-aggregator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8021"))
DB_NAME = os.getenv("DB_NAME", "research")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

EXCHANGES = ["binance", "coinbase", "kraken", "paper"]
redis_client = None
db_conn = None
subscriptions = []

class SubscribeRequest(BaseModel):
    exchange: str
    symbols: list[str]

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
    if redis_client: await redis_client.aclose()
    if db_conn: db_conn.close()

app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "db": db_conn is not None and not db_conn.closed, "redis": redis_client is not None}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/feeds")
async def list_feeds():
    return [
        {
            "exchange": ex,
            "status": "connected",
            "symbols_tracked": 5,
            "last_update": datetime.now(timezone.utc).isoformat(),
        }
        for ex in EXCHANGES
    ]

@app.get("/feeds/subscriptions")
async def list_subscriptions():
    return subscriptions

@app.get("/feeds/{exchange}")
async def get_feed(exchange: str):
    if exchange not in EXCHANGES:
        raise HTTPException(status_code=404, detail="Exchange not found")
    return {
        "exchange": exchange,
        "status": "connected",
        "symbols_tracked": 5,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }

@app.post("/feeds/subscribe")
async def subscribe(body: SubscribeRequest):
    if body.exchange not in EXCHANGES:
        raise HTTPException(status_code=400, detail="Unknown exchange")
    sub = {
        "subscription_id": str(uuid.uuid4()),
        "exchange": body.exchange,
        "symbols": body.symbols,
        "subscribed_at": datetime.now(timezone.utc).isoformat(),
    }
    subscriptions.append(sub)
    return sub

@app.get("/quotes/{symbol}")
async def get_quote(symbol: str):
    import random
    price = round(random.uniform(100, 50000), 2)
    return {
        "symbol": symbol,
        "best_bid": price,
        "best_ask": round(price + 0.1, 2),
        "spread": 0.1,
        "sources": EXCHANGES,
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
