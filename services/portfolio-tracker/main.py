import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "portfolio-tracker")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8012"))
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

# symbol -> position dict
positions: dict[str, dict] = {
    "AAPL": {"symbol": "AAPL", "quantity": 100.0, "avg_price": 178.50, "side": "long",
             "current_value": 18250.0, "pnl_today": 125.50, "pnl_total": 400.0},
    "TSLA": {"symbol": "TSLA", "quantity": 50.0, "avg_price": 245.00, "side": "long",
             "current_value": 12400.0, "pnl_today": -75.25, "pnl_total": -100.0},
}


class PositionCreate(BaseModel):
    symbol: str
    quantity: float
    avg_price: float
    side: str  # "long" | "short"


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


@app.get("/portfolio")
async def get_portfolio():
    total_value = sum(p.get("current_value", p["quantity"] * p["avg_price"]) for p in positions.values())
    pnl_today = sum(p.get("pnl_today", 0.0) for p in positions.values())
    pnl_total = sum(p.get("pnl_total", 0.0) for p in positions.values())
    return {"total_value": round(total_value, 2), "cash": 100000.0,
            "positions_count": len(positions), "pnl_today": round(pnl_today, 2),
            "pnl_total": round(pnl_total, 2)}


@app.get("/positions")
async def list_positions():
    return list(positions.values())


@app.post("/positions", status_code=201)
async def add_position(req: PositionCreate):
    position = {"symbol": req.symbol, "quantity": req.quantity, "avg_price": req.avg_price,
                "side": req.side, "current_value": req.quantity * req.avg_price,
                "pnl_today": 0.0, "pnl_total": 0.0}
    positions[req.symbol] = position
    return position


@app.get("/positions/{symbol}")
async def get_position(symbol: str):
    if symbol not in positions:
        raise HTTPException(status_code=404, detail="Position not found")
    return positions[symbol]


@app.delete("/positions/{symbol}", status_code=204)
async def close_position(symbol: str):
    if symbol not in positions:
        raise HTTPException(status_code=404, detail="Position not found")
    del positions[symbol]


@app.get("/pnl")
async def get_pnl():
    return {"realized": 2340.50, "unrealized": 890.25, "total": 3230.75, "trades_count": 47}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
