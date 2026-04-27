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

SERVICE_NAME = os.getenv("SERVICE_NAME", "banks-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8009"))
DB_NAME = os.getenv("DB_NAME", "banks")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None
deployments: list[dict] = []


class DeployRequest(BaseModel):
    service_name: str
    image_tag: str
    strategy: str  # "blue-green" | "rolling"


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
    if redis_client:
        await redis_client.aclose()
    if db_conn:
        db_conn.close()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME,
            "db": db_conn is not None and not db_conn.closed,
            "redis": redis_client is not None}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/deploy")
async def deploy(req: DeployRequest):
    deployment = {
        "deployment_id": str(uuid.uuid4()),
        "status": "initiated",
        "service_name": req.service_name,
        "image_tag": req.image_tag,
        "strategy": req.strategy,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    deployments.insert(0, deployment)
    if len(deployments) > 20:
        deployments.pop()
    return deployment


@app.get("/deployments")
async def list_deployments():
    return deployments[:20]


@app.get("/deployments/{deployment_id}")
async def get_deployment(deployment_id: str):
    for d in deployments:
        if d["deployment_id"] == deployment_id:
            return d
    raise HTTPException(status_code=404, detail="Deployment not found")


@app.post("/deployments/{deployment_id}/rollback")
async def rollback_deployment(deployment_id: str):
    for d in deployments:
        if d["deployment_id"] == deployment_id:
            d["status"] = "rolled_back"
            return d
    raise HTTPException(status_code=404, detail="Deployment not found")


@app.get("/health/deployments")
async def health_deployments():
    active = sum(1 for d in deployments if d["status"] == "active")
    return {"active": active, "total": len(deployments)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
