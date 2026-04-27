import os, time, logging, random
from contextlib import asynccontextmanager
import psycopg2
import redis as redis_lib
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "api-proxy")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8001"))
DB_NAME = os.getenv("DB_NAME", "tank")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
START_TIME = time.time()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
INIT_SQL = "SELECT 1"
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
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/proxy/market")
def proxy_market(symbol: str = "BTCUSDT"):
    REQ.labels("GET", "/proxy/market", "200").inc()
    base = 45000 + random.uniform(0, 10000)
    return {
        "symbol": symbol,
        "open": round(base, 2),
        "high": round(base * 1.02, 2),
        "low": round(base * 0.98, 2),
        "close": round(base * (1 + random.uniform(-0.01, 0.01)), 2),
        "volume": round(random.uniform(1000, 5000), 2),
        "ts": int(time.time()),
    }


@app.get("/proxy/news")
def proxy_news(topic: str = "bitcoin"):
    REQ.labels("GET", "/proxy/news", "200").inc()
    sentiments = ["bullish", "bearish", "neutral"]
    sources = ["CoinDesk", "Bloomberg", "Reuters"]
    items = [
        {
            "title": f"{topic.capitalize()} {['surges', 'dips', 'stabilizes'][i % 3]} amid market activity",
            "source": sources[i % 3],
            "sentiment": sentiments[i % 3],
            "ts": int(time.time()) - i * 3600,
        }
        for i in range(3)
    ]
    return {"topic": topic, "items": items}


@app.get("/proxy/sentiment")
def proxy_sentiment(symbol: str = "BTC"):
    REQ.labels("GET", "/proxy/sentiment", "200").inc()
    score = round(random.uniform(0.4, 0.9), 2)
    label = "bullish" if score >= 0.6 else ("bearish" if score <= 0.4 else "neutral")
    return {"symbol": symbol, "score": score, "label": label, "ts": int(time.time())}


@app.get("/proxy/price")
def proxy_price(symbol: str = "BTC"):
    REQ.labels("GET", "/proxy/price", "200").inc()
    price = round(random.uniform(45000, 55000), 2)
    change = round(random.uniform(-3.0, 3.0), 2)
    return {"symbol": symbol, "price": price, "change_24h": change, "ts": int(time.time())}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
