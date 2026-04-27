import os, time, logging, random
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "market-data")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8013"))
DB_NAME = os.getenv("DB_NAME", "research")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
DEFAULT_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "binance")
START_TIME = time.time()
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
db = None
r = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT,
    interval TEXT DEFAULT '1m',
    ts TIMESTAMP DEFAULT NOW()
);
"""

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

def mock_ohlcv(symbol, n=10):
    rows = []
    base = 50000.0
    for i in range(n):
        o = base + random.uniform(-200, 200)
        h = o + random.uniform(0, 300)
        lo = o - random.uniform(0, 300)
        c = lo + random.uniform(0, h - lo)
        rows.append({"symbol": symbol, "exchange": DEFAULT_EXCHANGE, "open": round(o, 2),
                     "high": round(h, 2), "low": round(lo, 2), "close": round(c, 2),
                     "volume": round(random.uniform(100, 5000), 4), "interval": "1m"})
        base = c
    return rows

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

@app.get("/ohlcv")
def get_ohlcv(symbol: str = "BTCUSDT", limit: int = 100):
    REQ.labels("GET", "/ohlcv", "200").inc()
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM ohlcv WHERE symbol=%s ORDER BY ts DESC LIMIT %s",
                    (symbol, limit))
                rows = cur.fetchall()
            if rows:
                return {"symbol": symbol, "data": [dict(r) for r in rows]}
        except Exception as e:
            logger.warning("DB query error: %s", e)
    return {"symbol": symbol, "data": mock_ohlcv(symbol, min(limit, 10)), "source": "mock"}

@app.post("/ohlcv")
def post_ohlcv(body: dict):
    REQ.labels("POST", "/ohlcv", "200").inc()
    required = {"symbol", "exchange", "open", "high", "low", "close", "volume"}
    if not required.issubset(body):
        raise HTTPException(400, f"Missing fields: {required - set(body)}")
    if db and not db.closed:
        try:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO ohlcv(symbol,exchange,open,high,low,close,volume,interval) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (body["symbol"], body["exchange"], body["open"], body["high"],
                     body["low"], body["close"], body["volume"], body.get("interval", "1m")))
                row_id = cur.fetchone()[0]
            db.commit()
            return {"ok": True, "id": row_id}
        except Exception as e:
            db.rollback()
            raise HTTPException(500, str(e))
    return {"ok": True, "id": None, "note": "DB unavailable"}

@app.get("/ticker")
def get_ticker(symbol: str = "BTCUSDT"):
    REQ.labels("GET", "/ticker", "200").inc()
    price = 50000 + random.uniform(-500, 500)
    spread = random.uniform(1, 10)
    return {"symbol": symbol, "price": round(price, 2), "bid": round(price - spread, 2),
            "ask": round(price + spread, 2), "volume_24h": round(random.uniform(10000, 50000), 2),
            "ts": time.time()}

@app.get("/orderbook")
def get_orderbook(symbol: str = "BTCUSDT"):
    REQ.labels("GET", "/orderbook", "200").inc()
    mid = 50000 + random.uniform(-500, 500)
    bids = [[round(mid - i * 5 - random.uniform(0, 2), 2), round(random.uniform(0.1, 2), 4)]
            for i in range(5)]
    asks = [[round(mid + i * 5 + random.uniform(0, 2), 2), round(random.uniform(0.1, 2), 4)]
            for i in range(5)]
    return {"symbol": symbol, "bids": bids, "asks": asks, "ts": time.time()}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
