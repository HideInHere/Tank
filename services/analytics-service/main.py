import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "analytics-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8024"))
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

redis_client = None
db_conn = None

MOCK_SYMBOLS = [
    {"symbol": "BTC-USD", "trades": 78, "total_pnl": 9240.50, "win_rate": 0.628},
    {"symbol": "ETH-USD", "trades": 54, "total_pnl": 4310.25, "win_rate": 0.574},
    {"symbol": "SOL-USD", "trades": 41, "total_pnl": 2180.00, "win_rate": 0.561},
    {"symbol": "BNB-USD", "trades": 38, "total_pnl": 1620.75, "win_rate": 0.526},
    {"symbol": "AVAX-USD", "trades": 36, "total_pnl": 1079.00, "win_rate": 0.500},
]

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

@app.get("/analytics/summary")
async def summary():
    return {
        "total_trades": 247,
        "winning_trades": 143,
        "win_rate": 0.579,
        "avg_return_pct": 0.0082,
        "total_pnl": 18430.50,
        "period": "all_time",
    }

@app.get("/analytics/performance")
async def performance():
    return {
        "sharpe_ratio": 1.87,
        "sortino_ratio": 2.34,
        "calmar_ratio": 3.12,
        "max_drawdown": -0.089,
        "volatility_annual": 0.142,
        "beta": 0.73,
    }

@app.get("/analytics/risk")
async def risk():
    return {
        "var_95": -2340,
        "var_99": -4120,
        "cvar_95": -3100,
        "portfolio_beta": 0.73,
        "correlation_spy": 0.45,
    }

@app.get("/analytics/trades")
async def trades(limit: int = 50, offset: int = 0):
    import random
    base_time = datetime.now(timezone.utc)
    mock_trades = []
    symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD"]
    for i in range(10):
        entry_price = round(random.uniform(100, 50000), 2)
        exit_price = round(entry_price * random.uniform(0.97, 1.05), 2)
        qty = round(random.uniform(0.01, 2.0), 4)
        pnl = round((exit_price - entry_price) * qty, 2)
        entry_dt = base_time - timedelta(hours=random.randint(1, 720))
        exit_dt = entry_dt + timedelta(minutes=random.randint(5, 480))
        mock_trades.append({
            "trade_id": str(uuid.uuid4()),
            "symbol": random.choice(symbols),
            "side": random.choice(["buy", "sell"]),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
            "pnl": pnl,
            "return_pct": round((exit_price - entry_price) / entry_price, 6),
            "entry_time": entry_dt.isoformat(),
            "exit_time": exit_dt.isoformat(),
        })
    return mock_trades[offset: offset + limit]

@app.get("/analytics/symbols")
async def symbols():
    return MOCK_SYMBOLS

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
