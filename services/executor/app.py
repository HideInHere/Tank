import os, time, logging, json, uuid
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import httpx, uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed
from pydantic import BaseModel
from typing import Optional
import random

SERVICE_NAME = os.getenv("SERVICE_NAME", "executor")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8004"))
DB_NAME = os.getenv("DB_NAME", "executor")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
ALPACA_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET", "")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"
START_TIME = time.time()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])

INIT_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty FLOAT NOT NULL,
    order_type TEXT DEFAULT 'market',
    status TEXT DEFAULT 'pending',
    filled_qty FLOAT DEFAULT 0,
    avg_price FLOAT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
"""

db = None
r = None


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def connect_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASS, dbname=DB_NAME, connect_timeout=5,
    )


@asynccontextmanager
async def lifespan(app):
    global db, r
    try:
        db = connect_db()
        with db.cursor() as cur:
            cur.execute(INIT_SQL)
        db.commit()
        logger.info("DB connected: %s", DB_NAME)
    except Exception as e:
        logger.warning("DB error: %s", e)
    try:
        r = redis_lib.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS,
            decode_responses=True, socket_connect_timeout=3,
        )
        r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis error: %s", e)
    yield
    if db and not db.closed:
        db.close()


app = FastAPI(title=SERVICE_NAME, version="1.0.0", lifespan=lifespan)


class ExecuteIn(BaseModel):
    symbol: str
    side: str
    qty: float
    order_type: str = "market"
    limit_price: Optional[float] = None


@app.get("/health")
def health():
    db_ok = bool(db and not db.closed)
    try:
        r_ok = bool(r and r.ping())
    except Exception:
        r_ok = False
    return {
        "status": "healthy", "service": SERVICE_NAME,
        "db": db_ok, "redis": r_ok,
        "uptime": round(time.time() - START_TIME),
        "paper_trading": PAPER_TRADING,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/execute", status_code=201)
async def execute_order(body: ExecuteIn):
    REQ.labels("POST", "/execute", "201").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    order_id = str(uuid.uuid4())
    avg_price = None
    status = "pending"
    filled_qty = 0.0
    meta = {}
    if PAPER_TRADING:
        avg_price = round(random.uniform(45000, 55000), 2)
        status = "filled"
        filled_qty = body.qty
        meta = {"paper": True, "simulated_price": avg_price}
    else:
        try:
            payload = {
                "symbol": body.symbol, "side": body.side,
                "qty": str(body.qty), "type": body.order_type,
                "time_in_force": "gtc",
            }
            if body.order_type == "limit" and body.limit_price:
                payload["limit_price"] = str(body.limit_price)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://paper-api.alpaca.markets/v2/orders",
                    json=payload,
                    headers={
                        "APCA-API-KEY-ID": ALPACA_KEY,
                        "APCA-API-SECRET-KEY": ALPACA_SECRET,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                order_id = data.get("id", order_id)
                status = data.get("status", "pending")
                meta = data
        except Exception as e:
            logger.warning("Alpaca API error: %s", e)
            status = "error"
            meta = {"error": str(e)}
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """INSERT INTO orders (id, symbol, side, qty, order_type, status, filled_qty, avg_price, metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING *""",
            (order_id, body.symbol, body.side, body.qty, body.order_type,
             status, filled_qty, avg_price, json.dumps(meta)),
        )
        row = dict(cur.fetchone())
    db.commit()
    return row


@app.get("/orders")
def list_orders(limit: int = 50):
    REQ.labels("GET", "/orders", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    return {"orders": [dict(r) for r in rows], "count": len(rows)}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    REQ.labels("GET", "/orders/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Order not found")
    return dict(row)


@app.delete("/orders/{order_id}")
def cancel_order(order_id: str):
    REQ.labels("DELETE", "/orders/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    with db.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "UPDATE orders SET status='cancelled', updated_at=NOW() WHERE id=%s RETURNING *",
            (order_id,),
        )
        row = cur.fetchone()
    db.commit()
    if not row:
        raise HTTPException(404, "Order not found")
    return dict(row)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
