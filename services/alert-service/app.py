import os, time, logging
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import httpx, uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "alert-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8017"))
DB_NAME = os.getenv("DB_NAME", "tank")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
START_TIME = time.time()
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
db = None
r = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    channel TEXT NOT NULL,
    level TEXT DEFAULT 'info' CHECK(level IN ('info','warning','critical')),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
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

async def send_telegram(title: str, message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": f"{title}: {message}"})
            return resp.status_code == 200
    except Exception as e:
        logger.warning("Telegram error: %s", e)
        return False

async def send_slack(title: str, message: str) -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json={"text": f"{title}: {message}"})
            return resp.status_code == 200
    except Exception as e:
        logger.warning("Slack error: %s", e)
        return False

async def send_discord(title: str, message: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(DISCORD_WEBHOOK_URL,
                                     json={"content": f"**{title}**: {message}"})
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning("Discord error: %s", e)
        return False

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

@app.post("/alert")
async def create_alert(body: dict):
    REQ.labels("POST", "/alert", "200").inc()
    for f in ("channel", "title", "message"):
        if f not in body:
            raise HTTPException(400, f"Missing field: {f}")
    channel = body["channel"]
    level = body.get("level", "info")
    title = body["title"]
    message = body["message"]
    alert_id = None
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO alerts(channel,level,title,message) VALUES(%s,%s,%s,%s) RETURNING id",
                    (channel, level, title, message))
                alert_id = cur.fetchone()["id"]
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("DB insert error: %s", e)
    delivered = False
    channels = [channel] if channel != "all" else ["telegram", "slack", "discord"]
    for ch in channels:
        if ch == "telegram":
            delivered = delivered or await send_telegram(title, message)
        elif ch == "slack":
            delivered = delivered or await send_slack(title, message)
        elif ch == "discord":
            delivered = delivered or await send_discord(title, message)
    if alert_id and db and not db.closed:
        try:
            with db.cursor() as cur:
                cur.execute("UPDATE alerts SET delivered=%s WHERE id=%s", (delivered, alert_id))
            db.commit()
        except Exception:
            db.rollback()
    return {"ok": True, "alert_id": alert_id, "delivered": delivered}

@app.get("/alerts")
def list_alerts(limit: int = 50):
    REQ.labels("GET", "/alerts", "200").inc()
    if db and not db.closed:
        try:
            with db.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT %s", (limit,))
                return {"alerts": [dict(r) for r in cur.fetchall()]}
        except Exception as e:
            logger.warning("DB query error: %s", e)
    return {"alerts": [], "note": "DB unavailable"}

@app.get("/channels")
def get_channels():
    REQ.labels("GET", "/channels", "200").inc()
    return {"telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
            "slack": bool(SLACK_WEBHOOK_URL),
            "discord": bool(DISCORD_WEBHOOK_URL)}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
