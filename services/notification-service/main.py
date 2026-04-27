import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8023"))
DB_NAME = os.getenv("DB_NAME", "tank")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None
channels = {}
notifications = []

class ChannelCreate(BaseModel):
    type: str
    config: dict
    name: str

class SendRequest(BaseModel):
    channel_id: str
    message: str
    subject: Optional[str] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, db_conn
    redis_client = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
        encoding="utf-8", decode_responses=True
    )
    try:
        db_conn = psycopg2.connect(host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=DB_NAME, user=POSTGRES_USER, password=POSTGRES_PASSWORD)
    except Exception as e:
        log.warning("db_connect_failed", error=str(e))
    if TELEGRAM_BOT_TOKEN:
        tg_id = str(uuid.uuid4())
        channels[tg_id] = {"id": tg_id, "type": "telegram", "config": {"chat_id": "***"}, "name": "telegram-default", "active": True}
    log.info("service_started", service=SERVICE_NAME)
    yield
    if redis_client: await redis_client.aclose()
    if db_conn: db_conn.close()

app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "db": db_conn is not None and not db_conn.closed, "redis": redis_client is not None}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/channels")
async def list_channels():
    return list(channels.values())

@app.post("/channels")
async def create_channel(body: ChannelCreate):
    channel_id = str(uuid.uuid4())
    masked_config = {k: ("***" if "token" in k.lower() or "secret" in k.lower() else v) for k, v in body.config.items()}
    record = {"id": channel_id, "type": body.type, "config": masked_config, "name": body.name, "active": True}
    channels[channel_id] = record
    return {"channel_id": channel_id, "type": body.type, "name": body.name, "active": True}

@app.post("/send")
async def send_notification(body: SendRequest):
    if body.channel_id not in channels:
        raise HTTPException(status_code=404, detail="Channel not found")
    notif = {
        "notification_id": str(uuid.uuid4()),
        "channel_id": body.channel_id,
        "message": body.message,
        "subject": body.subject,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "status": "sent",
    }
    notifications.append(notif)
    return notif

@app.get("/history")
async def get_history():
    return notifications[-50:]

@app.get("/history/{notification_id}")
async def get_notification(notification_id: str):
    for n in notifications:
        if n["notification_id"] == notification_id:
            return n
    raise HTTPException(status_code=404, detail="Notification not found")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
