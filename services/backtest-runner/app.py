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

SERVICE_NAME = os.getenv("SERVICE_NAME", "backtest-runner")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8019"))
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
CREATE TABLE IF NOT EXISTS backtests (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    params JSONB DEFAULT '{}',
    results JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
"""

STRATEGIES_INFO = {
    "sma_crossover": "Simple Moving Average crossover strategy",
    "rsi_divergence": "RSI divergence detection strategy",
    "macd": "MACD histogram signal strategy",
    "bollinger": "Bollinger Band mean reversion strategy",
    "momentum": "Price momentum breakout strategy",
    "mean_reversion": "Statistical mean reversion strategy",
}

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

def compute_mock_results(strategy: str, symbol: str, params: dict) -> dict:
    rng = random.Random(hash(f"{strategy}{symbol}") ^ int(time.time()))
    return_pct = round(rng.uniform(-20, 80), 2)
    sharpe = round(rng.uniform(0.2, 2.8), 3)
    max_dd = round(rng.uniform(-0.35, -0.02), 4)
    num_trades = rng.randint(20, 500)
    win_rate = round(rng.uniform(0.35, 0.70), 3)
    return {"return_pct": return_pct, "sharpe_ratio": sharpe, "max_drawdown": max_dd,
            "num_trades": num_trades, "win_rate": win_rate}

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

@app.post("/run")
def run_backtest(body: dict):
    REQ.labels("POST", "/run", "200").inc()
    for f in ("strategy", "symbol", "start_date", "end_date"):
        if f not in body:
            raise HTTPException(400, f"Missing field: {f}")
    strategy = body["strategy"]
    symbol = body["symbol"]
    start_date = body["start_date"]
    end_date = body["end_date"]
    params = body.get("params", {})
    results = compute_mock_results(strategy, symbol, params)
    if not db or db.closed:
        return {"strategy": strategy, "symbol": symbol, "results": results,
                "status": "completed", "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO backtests(strategy,symbol,start_date,end_date,params,results,status,completed_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,'completed',NOW()) RETURNING *",
                (strategy, symbol, start_date, end_date, json.dumps(params), json.dumps(results)))
            row = dict(cur.fetchone())
        db.commit()
        return row
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/backtests")
def list_backtests(strategy: str = "", limit: int = 20):
    REQ.labels("GET", "/backtests", "200").inc()
    if not db or db.closed:
        return {"backtests": [], "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            if strategy:
                cur.execute(
                    "SELECT * FROM backtests WHERE strategy=%s ORDER BY created_at DESC LIMIT %s",
                    (strategy, limit))
            else:
                cur.execute("SELECT * FROM backtests ORDER BY created_at DESC LIMIT %s", (limit,))
            return {"backtests": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/backtests/{bt_id}")
def get_backtest(bt_id: str):
    REQ.labels("GET", "/backtests/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM backtests WHERE id=%s", (bt_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Backtest not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/strategies")
def list_strategies():
    REQ.labels("GET", "/strategies", "200").inc()
    return {"strategies": STRATEGIES_INFO}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
