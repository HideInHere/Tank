import os, time, logging, random, hashlib, json
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "signal-generator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8014"))
DB_NAME = os.getenv("DB_NAME", "decision")
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
CREATE TABLE IF NOT EXISTS generated_signals (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    strength FLOAT,
    params JSONB DEFAULT '{}',
    generated_at TIMESTAMP DEFAULT NOW()
);
"""

STRATEGIES = ["sma_crossover", "rsi_divergence", "macd", "bollinger", "momentum", "mean_reversion"]

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

def compute_signal(symbol: str, strategy: str) -> tuple[str, float]:
    seed = int(hashlib.md5(f"{symbol}{strategy}".encode()).hexdigest(), 16)
    rng = random.Random(seed ^ int(time.time() / 60))
    strength = round(rng.uniform(0, 1), 4)
    if strength > 0.6:
        sig_type = "long"
    elif strength < 0.4:
        sig_type = "short"
    else:
        sig_type = "neutral"
    return sig_type, strength

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

@app.post("/generate")
def generate_signal(body: dict):
    REQ.labels("POST", "/generate", "200").inc()
    symbol = body.get("symbol", "BTCUSDT")
    strategy = body.get("strategy", "sma_crossover")
    params = body.get("params", {})
    if strategy not in STRATEGIES:
        raise HTTPException(400, f"Unknown strategy. Available: {STRATEGIES}")
    sig_type, strength = compute_signal(symbol, strategy)
    signal = {"symbol": symbol, "strategy": strategy, "signal_type": sig_type,
              "strength": strength, "params": params}
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO generated_signals(symbol,strategy,signal_type,strength,params) "
                    "VALUES(%s,%s,%s,%s,%s) RETURNING *",
                    (symbol, strategy, sig_type, strength, json.dumps(params)))
                row = dict(cur.fetchone())
            db.commit()
            signal = row
        except Exception as e:
            db.rollback()
            logger.warning("DB insert error: %s", e)
    if r:
        try:
            r.publish(f"signals:{symbol}", json.dumps(signal, default=str))
        except Exception as e:
            logger.warning("Redis publish error: %s", e)
    return signal

@app.get("/signals")
def list_signals(symbol: str = "", limit: int = 20):
    REQ.labels("GET", "/signals", "200").inc()
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                if symbol:
                    cur.execute(
                        "SELECT * FROM generated_signals WHERE symbol ILIKE %s "
                        "ORDER BY generated_at DESC LIMIT %s", (f"%{symbol}%", limit))
                else:
                    cur.execute(
                        "SELECT * FROM generated_signals ORDER BY generated_at DESC LIMIT %s",
                        (limit,))
                return {"signals": [dict(r) for r in cur.fetchall()]}
        except Exception as e:
            logger.warning("DB query error: %s", e)
    return {"signals": [], "note": "DB unavailable"}

@app.get("/strategies")
def list_strategies():
    REQ.labels("GET", "/strategies", "200").inc()
    return {"strategies": STRATEGIES}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
