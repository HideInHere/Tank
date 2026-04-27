import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "executor")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8004"))
DB_NAME = os.getenv("DB_NAME", "executor")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])

redis_client = None
db_conn = None
orders_store: dict = {}

class OrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    order_type: str
    price: Optional[float] = None

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

@app.post("/orders")
async def create_order(req: OrderRequest):
    order_id = str(uuid.uuid4())
    exchange = "paper-exchange" if PAPER_TRADING else "live-exchange"
    order = {"order_id": order_id, "status": "submitted", "symbol": req.symbol.upper(), "side": req.side, "quantity": req.quantity, "price": req.price, "order_type": req.order_type, "exchange": exchange}
    orders_store[order_id] = order
    return order

@app.get("/orders")
async def list_orders():
    return list(orders_store.values())

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    order = orders_store.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.delete("/orders/{order_id}")
async def cancel_order(order_id: str):
    order = orders_store.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    orders_store[order_id]["status"] = "cancelled"
    return orders_store[order_id]

@app.get("/positions")
async def get_positions():
    return [
        {"symbol": "AAPL", "quantity": 100, "avg_price": 148.50, "current_price": 150.0, "pnl": 150.0, "pnl_pct": 1.01},
        {"symbol": "NVDA", "quantity": 50, "avg_price": 820.0, "current_price": 875.0, "pnl": 2750.0, "pnl_pct": 6.71},
    ]

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
