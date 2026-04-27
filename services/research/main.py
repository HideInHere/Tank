import os
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

SERVICE_NAME = os.getenv("SERVICE_NAME", "research")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8002"))
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
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])

redis_client = None
db_conn = None

MOCK_SIGNALS = [
    {"symbol": "AAPL", "signal_type": "buy", "strength": 0.82, "source": "momentum", "timestamp": "2026-04-27T10:00:00Z"},
    {"symbol": "TSLA", "signal_type": "sell", "strength": 0.74, "source": "mean_reversion", "timestamp": "2026-04-27T10:05:00Z"},
    {"symbol": "NVDA", "signal_type": "buy", "strength": 0.91, "source": "momentum", "timestamp": "2026-04-27T10:10:00Z"},
    {"symbol": "MSFT", "signal_type": "hold", "strength": 0.55, "source": "mean_reversion", "timestamp": "2026-04-27T10:15:00Z"},
    {"symbol": "GOOGL", "signal_type": "buy", "strength": 0.67, "source": "momentum", "timestamp": "2026-04-27T10:20:00Z"},
]

class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    start_date: str
    end_date: str

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

@app.get("/signals")
async def get_signals():
    return MOCK_SIGNALS

@app.get("/signals/{symbol}")
async def get_symbol_signals(symbol: str):
    results = [s for s in MOCK_SIGNALS if s["symbol"] == symbol.upper()]
    if not results:
        raise HTTPException(status_code=404, detail=f"No signals for {symbol}")
    return results

@app.post("/backtest")
async def run_backtest(req: BacktestRequest):
    return {
        "strategy": req.strategy,
        "symbol": req.symbol,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "sharpe": 1.42,
        "max_drawdown": -0.12,
        "total_return": 0.34,
        "trades": 127,
    }

@app.get("/analysis/{symbol}")
async def get_analysis(symbol: str):
    return {
        "symbol": symbol.upper(),
        "rsi": 58.3,
        "macd": 0.45,
        "bollinger": "neutral",
        "recommendation": "hold",
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
