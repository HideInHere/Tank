import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn
import redis.asyncio as aioredis
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "api-proxy")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8001"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])

redis_client = None
db_conn = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
        encoding="utf-8", decode_responses=True
    )
    log.info("service_started", service=SERVICE_NAME, port=SERVICE_PORT)
    yield
    if redis_client:
        await redis_client.aclose()

app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "db": False, "redis": redis_client is not None}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/market/quote/{symbol}")
async def get_quote(symbol: str):
    REQUEST_COUNT.labels("GET", "/market/quote", "200").inc()
    return {
        "symbol": symbol.upper(),
        "price": 150.0,
        "change_pct": 0.5,
        "volume": 1000000,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/market/news/{symbol}")
async def get_news(symbol: str):
    REQUEST_COUNT.labels("GET", "/market/news", "200").inc()
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"headline": f"{symbol.upper()} beats Q2 earnings expectations", "source": "Reuters", "sentiment_score": 0.82, "published_at": now},
        {"headline": f"Analysts raise {symbol.upper()} price target to $175", "source": "Bloomberg", "sentiment_score": 0.71, "published_at": now},
        {"headline": f"{symbol.upper()} faces regulatory scrutiny in EU markets", "source": "FT", "sentiment_score": -0.35, "published_at": now},
    ]

@app.get("/market/sentiment/{symbol}")
async def get_sentiment(symbol: str):
    REQUEST_COUNT.labels("GET", "/market/sentiment", "200").inc()
    return {"symbol": symbol.upper(), "sentiment": 0.65, "bullish_pct": 65, "bearish_pct": 35}

@app.get("/market/ohlcv/{symbol}")
async def get_ohlcv(symbol: str):
    REQUEST_COUNT.labels("GET", "/market/ohlcv", "200").inc()
    base = 148.0
    candles = []
    for i in range(5):
        o = base + i * 0.5
        candles.append({"open": o, "high": o + 1.2, "low": o - 0.8, "close": o + 0.7, "volume": 900000 + i * 50000, "timestamp": f"2026-04-2{i+1}T16:00:00Z"})
    return {"symbol": symbol.upper(), "candles": candles}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
