import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from typing import Optional
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "risk-manager")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8011"))
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

redis_client = None
db_conn = None

risk_limits = {
    "max_position_size": float(os.getenv("RISK_MAX_POSITION_SIZE", "10000")),
    "max_daily_loss": float(os.getenv("RISK_MAX_DAILY_LOSS", "5000")),
    "max_drawdown_pct": float(os.getenv("RISK_MAX_DRAWDOWN_PCT", "15")),
}


class TradeCheck(BaseModel):
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    price: float


class LimitsUpdate(BaseModel):
    max_position_size: Optional[float] = None
    max_daily_loss: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


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


@app.post("/check")
async def check_trade(req: TradeCheck):
    trade_value = req.quantity * req.price
    approved = trade_value <= risk_limits["max_position_size"]
    daily_loss_pct = 3.2  # mock current daily loss %
    if daily_loss_pct >= risk_limits["max_drawdown_pct"]:
        approved = False
    risk_score = min(trade_value / risk_limits["max_position_size"], 1.0)
    reason = None if approved else (
        "Trade value exceeds max position size" if trade_value > risk_limits["max_position_size"]
        else "Daily drawdown limit reached"
    )
    return {"approved": approved, "reason": reason, "trade_value": trade_value, "risk_score": round(risk_score, 4)}


@app.get("/limits")
async def get_limits():
    return risk_limits


@app.put("/limits")
async def update_limits(req: LimitsUpdate):
    if req.max_position_size is not None:
        risk_limits["max_position_size"] = req.max_position_size
    if req.max_daily_loss is not None:
        risk_limits["max_daily_loss"] = req.max_daily_loss
    if req.max_drawdown_pct is not None:
        risk_limits["max_drawdown_pct"] = req.max_drawdown_pct
    return risk_limits


@app.get("/exposure")
async def get_exposure():
    return {"total_long": 45000, "total_short": 12000, "net": 33000, "utilization_pct": 45.0}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
