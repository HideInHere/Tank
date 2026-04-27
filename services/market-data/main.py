import os, random
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "market-data")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8013"))
DB_NAME = os.getenv("DB_NAME", "research")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
DEFAULT_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "paper")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None

SUPPORTED_EXCHANGES = ["binance", "coinbase", "kraken", "paper"]


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


@app.get("/ticker/{symbol}")
async def get_ticker(symbol: str):
    base_price = 150.0 + random.uniform(-2.0, 2.0)
    spread = round(random.uniform(0.03, 0.08), 2)
    return {"symbol": symbol.upper(), "price": round(base_price, 4),
            "bid": round(base_price - spread, 4), "ask": round(base_price + spread, 4),
            "volume": random.randint(500000, 5000000), "exchange": DEFAULT_EXCHANGE,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, interval: str = "1h", limit: int = 100):
    candles = []
    now = datetime.now(timezone.utc)
    close = 150.0
    for i in range(10):
        ts = now - timedelta(hours=10 - i)
        open_ = close + random.uniform(-1.5, 1.5)
        high = open_ + random.uniform(0.5, 2.5)
        low = open_ - random.uniform(0.5, 2.5)
        close = open_ + random.uniform(-1.0, 1.0)
        candles.append({"timestamp": ts.isoformat(), "open": round(open_, 4),
                        "high": round(high, 4), "low": round(low, 4),
                        "close": round(close, 4), "volume": random.randint(10000, 100000)})
    return candles


@app.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str):
    mid = 150.0 + random.uniform(-1.0, 1.0)
    bids = [[round(mid - i * 0.05, 4), round(random.uniform(1.0, 50.0), 2)] for i in range(1, 6)]
    asks = [[round(mid + i * 0.05, 4), round(random.uniform(1.0, 50.0), 2)] for i in range(1, 6)]
    return {"symbol": symbol.upper(), "bids": bids, "asks": asks}


@app.get("/exchanges")
async def list_exchanges():
    return SUPPORTED_EXCHANGES


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
