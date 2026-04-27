import os, time, logging, random, json
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "feed-aggregator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8021"))
DB_NAME = os.getenv("DB_NAME", "research")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
START_TIME = time.time()
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
db = None
r = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS feed_subscriptions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    feed_type TEXT DEFAULT 'ohlcv',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS feed_data (
    id SERIAL PRIMARY KEY,
    subscription_id TEXT REFERENCES feed_subscriptions(id),
    data JSONB NOT NULL,
    received_at TIMESTAMP DEFAULT NOW()
);
"""

EXCHANGES = ["binance", "coinbase", "kraken"]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
FEED_TYPES = ["ohlcv", "ticker", "orderbook"]

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

def mock_feed_data(exchange: str, symbol: str, feed_type: str = "ohlcv") -> dict:
    base = {"exchange": exchange, "symbol": symbol, "ts": time.time()}
    if feed_type == "ohlcv":
        price = 50000 + random.uniform(-1000, 1000)
        base.update({"open": round(price, 2), "high": round(price + random.uniform(0, 200), 2),
                     "low": round(price - random.uniform(0, 200), 2),
                     "close": round(price + random.uniform(-100, 100), 2),
                     "volume": round(random.uniform(10, 500), 4)})
    elif feed_type == "ticker":
        price = 50000 + random.uniform(-500, 500)
        base.update({"price": round(price, 2), "bid": round(price - 5, 2),
                     "ask": round(price + 5, 2)})
    elif feed_type == "orderbook":
        mid = 50000 + random.uniform(-500, 500)
        base.update({"bids": [[round(mid - i * 5, 2), round(random.uniform(0.1, 2), 4)]
                               for i in range(5)],
                     "asks": [[round(mid + i * 5, 2), round(random.uniform(0.1, 2), 4)]
                               for i in range(5)]})
    return base

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

@app.post("/subscribe")
def subscribe(body: dict):
    REQ.labels("POST", "/subscribe", "200").inc()
    for f in ("exchange", "symbol"):
        if f not in body:
            raise HTTPException(400, f"Missing field: {f}")
    feed_type = body.get("feed_type", "ohlcv")
    if feed_type not in FEED_TYPES:
        raise HTTPException(400, f"feed_type must be one of {FEED_TYPES}")
    if not db or db.closed:
        return {"ok": True, "subscription_id": None, "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO feed_subscriptions(exchange,symbol,feed_type) VALUES(%s,%s,%s) RETURNING id",
                (body["exchange"], body["symbol"], feed_type))
            sub_id = cur.fetchone()["id"]
        db.commit()
        return {"ok": True, "subscription_id": sub_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/subscriptions")
def list_subscriptions():
    REQ.labels("GET", "/subscriptions", "200").inc()
    if not db or db.closed:
        return {"subscriptions": [], "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM feed_subscriptions WHERE active=TRUE ORDER BY created_at DESC")
            return {"subscriptions": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: str):
    REQ.labels("DELETE", "/subscriptions/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE feed_subscriptions SET active=FALSE WHERE id=%s", (sub_id,))
        db.commit()
        return {"ok": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/feeds")
def list_feeds():
    REQ.labels("GET", "/feeds", "200").inc()
    return {"exchanges": EXCHANGES, "symbols": SYMBOLS, "feed_types": FEED_TYPES}

@app.get("/latest/{exchange}/{symbol}")
def get_latest(exchange: str, symbol: str, feed_type: str = "ohlcv"):
    REQ.labels("GET", "/latest/{exchange}/{symbol}", "200").inc()
    return mock_feed_data(exchange, symbol, feed_type)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
