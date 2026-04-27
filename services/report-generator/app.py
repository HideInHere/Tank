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

SERVICE_NAME = os.getenv("SERVICE_NAME", "report-generator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8018"))
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
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    report_type TEXT NOT NULL,
    period_start TIMESTAMP,
    period_end TIMESTAMP,
    data JSONB DEFAULT '{}',
    generated_at TIMESTAMP DEFAULT NOW()
);
"""

REPORT_TYPES = ["daily", "weekly", "backtest"]

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

def generate_mock_data(report_type: str) -> dict:
    pnl = round(random.uniform(-5000, 15000), 2)
    trades = random.randint(10, 200)
    sharpe = round(random.uniform(0.5, 3.0), 3)
    max_dd = round(random.uniform(-0.25, -0.01), 4)
    win_rate = round(random.uniform(0.4, 0.75), 3)
    return {"report_type": report_type, "pnl": pnl, "trades": trades,
            "sharpe_ratio": sharpe, "max_drawdown": max_dd, "win_rate": win_rate,
            "generated_at": time.time()}

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
def generate_report(body: dict):
    REQ.labels("POST", "/generate", "200").inc()
    report_type = body.get("report_type", "daily")
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, f"report_type must be one of {REPORT_TYPES}")
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    data = generate_mock_data(report_type)
    if not db or db.closed:
        return {"report_type": report_type, "data": data, "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO reports(report_type,period_start,period_end,data) "
                "VALUES(%s,%s,%s,%s) RETURNING *",
                (report_type, period_start, period_end, json.dumps(data)))
            row = dict(cur.fetchone())
        db.commit()
        return row
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))

@app.get("/reports")
def list_reports(type: str = "", limit: int = 10):
    REQ.labels("GET", "/reports", "200").inc()
    if not db or db.closed:
        return {"reports": [], "note": "DB unavailable"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            if type:
                cur.execute(
                    "SELECT * FROM reports WHERE report_type=%s ORDER BY generated_at DESC LIMIT %s",
                    (type, limit))
            else:
                cur.execute("SELECT * FROM reports ORDER BY generated_at DESC LIMIT %s", (limit,))
            return {"reports": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/reports/{report_id}")
def get_report(report_id: str):
    REQ.labels("GET", "/reports/{id}", "200").inc()
    if not db or db.closed:
        raise HTTPException(503, "DB unavailable")
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM reports WHERE id=%s", (report_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Report not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/summary")
def get_summary():
    REQ.labels("GET", "/summary", "200").inc()
    if not db or db.closed:
        return {"message": "no reports yet"}
    try:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT data FROM reports WHERE report_type='daily' "
                "ORDER BY generated_at DESC LIMIT 1")
            row = cur.fetchone()
        if not row:
            return {"message": "no reports yet"}
        return row["data"]
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
