import os, time, logging, json
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import httpx, uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "order-router")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8015"))
DB_NAME = os.getenv("DB_NAME", "executor")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
EXECUTOR_URL = os.getenv("EXECUTOR_URL", "http://executor:8004")
START_TIME = time.time()
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
db = None
r = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS routed_orders (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    original_order_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty FLOAT NOT NULL,
    route TEXT NOT NULL,
    status TEXT DEFAULT 'routed',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
"""

ROUTING_TABLE = {
    "BTC": "binance", "ETH": "binance", "SOL": "binance",
    "AAPL": "alpaca", "TSLA": "alpaca",
    "default": "executor"
}

def determine_route(symbol: str) -> str:
    for prefix, route in ROUTING_TABLE.items():
        if prefix != "default" and symbol.upper().startswith(prefix):
            return route
    return ROUTING_TABLE["default"]

@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def connect_db():
    return psycopg2.connect(host=PG_HOST, port=PG_PORT, user=PG_USER,
                            password=PG_PASS, dbname=DB_NAME, connect_timeout=5)

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
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS,
                            decode_responses=True, socket_connect_timeout=3)
        r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis error: %s", e)
    yield
    if db and not db.closed:
        db.close()

app = FastAPI(title=SERVICE_NAME, version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health():
    db_ok = bool(db and not db.closed)
    try:
        r_ok = bool(r and r.ping())
    except Exception:
        r_ok = False
    return {"status": "healthy", "service": SERVICE_NAME, "db": db_ok, "redis": r_ok,
            "uptime": round(time.time() - START_TIME)}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/route")
async def route_order(body: dict):
    REQ.labels("POST", "/route", "200").inc()
    for field in ("symbol", "side", "qty"):
        if field not in body:
            raise HTTPException(400, f"Missing field: {field}")
    symbol = body["symbol"]
    route = determine_route(symbol)
    order_result = {"status": "forwarded", "route": route, "symbol": symbol,
                    "side": body["side"], "qty": body["qty"]}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{EXECUTOR_URL}/execute", json=body)
            order_result = resp.json()
    except Exception as e:
        logger.warning("Executor forwarding error: %s", e)
        order_result["note"] = "executor unreachable"
    record_id = None
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO routed_orders(symbol,side,qty,route,metadata) "
                    "VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (symbol, body["side"], body["qty"], route, json.dumps(order_result)))
                record_id = cur.fetchone()["id"]
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("DB insert error: %s", e)
    return {"ok": True, "route": route, "order": order_result, "record_id": record_id}

@app.get("/orders")
def list_orders(limit: int = 50):
    REQ.labels("GET", "/orders", "200").inc()
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM routed_orders ORDER BY created_at DESC LIMIT %s",
                            (limit,))
                return {"orders": [dict(r) for r in cur.fetchall()]}
        except Exception as e:
            logger.warning("DB query error: %s", e)
    return {"orders": [], "note": "DB unavailable"}

@app.get("/routes")
def get_routes():
    REQ.labels("GET", "/routes", "200").inc()
    return {"routes": ROUTING_TABLE}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
