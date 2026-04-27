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

SERVICE_NAME = os.getenv("SERVICE_NAME", "strategy-optimizer")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8020"))
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
CREATE TABLE IF NOT EXISTS optimizations (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    param_space JSONB DEFAULT '{}',
    best_params JSONB DEFAULT '{}',
    best_score FLOAT,
    iterations INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
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

def run_mock_optimization(param_space: dict, n_iter: int = 20) -> tuple[dict, float, int]:
    """Pick random combinations from param_space and return best."""
    best_params = {}
    best_score = -999.0
    for _ in range(n_iter):
        candidate = {k: random.choice(v) if isinstance(v, list) else v
                     for k, v in param_space.items()}
        score = random.uniform(0, 1)
        if score > best_score:
            best_score = score
            best_params = candidate
    return best_params, round(best_score, 4), n_iter

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

@app.post("/optimize")
def optimize(body: dict):
    REQ.labels("POST", "/optimize", "200").inc()
    for f in ("strategy", "symbol"):
        if f not in body:
            raise HTTPException(400, f"Missing field: {f}")
    strategy = body["strategy"]
    symbol = body["symbol"]
    param_space = body.get("param_space", {"sma_fast": [5, 10, 20], "sma_slow": [20, 50, 100]})
    best_params, best_score, iterations = run_mock_optimization(param_space)
    if not db or db.closed:
        return {"strategy": strategy, "symbol": symbol, "best_params": best_params,
                "best_score": best_score, "iterations": iterations, "status": "completed",
                "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO optimizations(strategy,symbol,param_space,best_params,best_score,iterations,status) "
                "VALUES(%s,%s,%s,%s,%s,%s,'completed') RETURNING *",
                (strategy, symbol, json.dumps(param_space), json.dumps(best_params),
                 best_score, iterations))
            row = dict(cur.fetchone())
        db.commit()
        return row
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/optimizations")
def list_optimizations(strategy: str = "", limit: int = 20):
    REQ.labels("GET", "/optimizations", "200").inc()
    if not db or db.closed:
        return {"optimizations": [], "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            if strategy:
                cur.execute(
                    "SELECT * FROM optimizations WHERE strategy=%s ORDER BY created_at DESC LIMIT %s",
                    (strategy, limit))
            else:
                cur.execute("SELECT * FROM optimizations ORDER BY created_at DESC LIMIT %s",
                            (limit,))
            return {"optimizations": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/optimizations/{opt_id}")
def get_optimization(opt_id: str):
    REQ.labels("GET", "/optimizations/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM optimizations WHERE id=%s", (opt_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Optimization not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/params/{strategy}")
def get_best_params(strategy: str):
    REQ.labels("GET", "/params/{strategy}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT best_params, best_score FROM optimizations "
                "WHERE strategy=%s AND status='completed' ORDER BY created_at DESC LIMIT 1",
                (strategy,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"No optimizations found for strategy: {strategy}")
        return {"strategy": strategy, "best_params": row["best_params"],
                "best_score": row["best_score"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
