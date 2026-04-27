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

SERVICE_NAME = os.getenv("SERVICE_NAME", "alert-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8017"))
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
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None
alerts = []

class AlertCreate(BaseModel):
    title: str
    message: str
    severity: str
    source: str

class NotifyRequest(BaseModel):
    channel: str
    message: str

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

@app.post("/alerts")
async def create_alert(body: AlertCreate):
    if body.severity not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="Invalid severity")
    alert = {
        "alert_id": str(uuid.uuid4()),
        "title": body.title,
        "message": body.message,
        "severity": body.severity,
        "source": body.source,
        "acknowledged": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    alerts.append(alert)
    return alert

@app.get("/alerts")
async def list_alerts(severity: Optional[str] = None):
    result = alerts[-50:]
    if severity:
        result = [a for a in result if a["severity"] == severity]
    return result

@app.put("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    for a in alerts:
        if a["alert_id"] == alert_id:
            a["acknowledged"] = True
            return a
    raise HTTPException(status_code=404, detail="Alert not found")

@app.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    for i, a in enumerate(alerts):
        if a["alert_id"] == alert_id:
            alerts.pop(i)
            return {"deleted": True, "alert_id": alert_id}
    raise HTTPException(status_code=404, detail="Alert not found")

@app.post("/notify")
async def notify(body: NotifyRequest):
    if body.channel not in ("telegram", "slack", "email"):
        raise HTTPException(status_code=400, detail="Invalid channel")
    return {"sent": True, "channel": body.channel, "message_preview": body.message[:50]}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
