import os, time, logging, json
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "position-manager")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8016"))
DB_NAME = os.getenv("DB_NAME", "ledger")
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
CREATE TABLE IF NOT EXISTS managed_positions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty FLOAT NOT NULL,
    entry_price FLOAT NOT NULL,
    current_price FLOAT,
    realized_pnl FLOAT DEFAULT 0,
    unrealized_pnl FLOAT DEFAULT 0,
    stop_loss FLOAT,
    take_profit FLOAT,
    status TEXT DEFAULT 'open',
    opened_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
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

def calc_unrealized(side, qty, entry, current):
    if current is None:
        return 0.0
    diff = current - entry
    return round(qty * diff if side == "long" else -qty * diff, 4)

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

@app.get("/positions")
def list_positions(status: str = "open"):
    REQ.labels("GET", "/positions", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM managed_positions WHERE status=%s ORDER BY opened_at DESC",
                        (status,))
            return {"positions": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/positions")
def create_position(body: dict):
    REQ.labels("POST", "/positions", "200").inc()
    for f in ("symbol", "side", "qty", "entry_price"):
        if f not in body:
            raise HTTPException(400, f"Missing field: {f}")
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO managed_positions(symbol,side,qty,entry_price,stop_loss,take_profit) "
                "VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (body["symbol"], body["side"], body["qty"], body["entry_price"],
                 body.get("stop_loss"), body.get("take_profit")))
            row = dict(cur.fetchone())
        db.commit()
        return row
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.put("/positions/{pos_id}")
def update_position(pos_id: str, body: dict):
    REQ.labels("PUT", "/positions/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM managed_positions WHERE id=%s", (pos_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Position not found")
            pos = dict(row)
            current_price = body.get("current_price", pos["current_price"])
            stop_loss = body.get("stop_loss", pos["stop_loss"])
            take_profit = body.get("take_profit", pos["take_profit"])
            status = body.get("status", pos["status"])
            upnl = calc_unrealized(pos["side"], pos["qty"], pos["entry_price"], current_price)
            cur.execute(
                "UPDATE managed_positions SET current_price=%s,stop_loss=%s,take_profit=%s,"
                "status=%s,unrealized_pnl=%s,updated_at=NOW() WHERE id=%s RETURNING *",
                (current_price, stop_loss, take_profit, status, upnl, pos_id))
            updated = dict(cur.fetchone())
        db.commit()
        return updated
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/pnl")
def get_pnl():
    REQ.labels("GET", "/pnl", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COALESCE(SUM(realized_pnl),0) AS total_realized, "
                "COALESCE(SUM(unrealized_pnl),0) AS total_unrealized, "
                "COUNT(*) AS position_count FROM managed_positions")
            row = dict(cur.fetchone())
        return {"total_realized": round(row["total_realized"], 4),
                "total_unrealized": round(row["total_unrealized"], 4),
                "position_count": row["position_count"]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/positions/{pos_id}/close")
def close_position(pos_id: str, body: dict):
    REQ.labels("POST", "/positions/{id}/close", "200").inc()
    exit_price = body.get("exit_price")
    if exit_price is None:
        raise HTTPException(400, "exit_price required")
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM managed_positions WHERE id=%s", (pos_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Position not found")
            pos = dict(row)
            realized = calc_unrealized(pos["side"], pos["qty"], pos["entry_price"], exit_price)
            cur.execute(
                "UPDATE managed_positions SET status='closed',current_price=%s,"
                "realized_pnl=%s,unrealized_pnl=0,updated_at=NOW() WHERE id=%s RETURNING *",
                (exit_price, realized, pos_id))
            updated = dict(cur.fetchone())
        db.commit()
        return updated
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
