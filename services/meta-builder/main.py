import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "meta-builder")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8010"))
DB_NAME = os.getenv("DB_NAME", "tank")
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
scaffolded_services: list[dict] = []

TEMPLATES = [
    {"name": "fastapi-service", "description": "Standard FastAPI microservice"},
    {"name": "grpc-service", "description": "gRPC service with protobuf"},
    {"name": "worker", "description": "Background task worker"},
]


class ServiceCreate(BaseModel):
    name: str
    template: str
    port: int


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


@app.get("/templates")
async def list_templates():
    return TEMPLATES


@app.post("/services", status_code=201)
async def create_service(req: ServiceCreate):
    svc = {
        "service_id": str(uuid.uuid4()),
        "name": req.name,
        "template": req.template,
        "port": req.port,
        "status": "scaffolded",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    scaffolded_services.append(svc)
    return svc


@app.get("/services")
async def list_services():
    return scaffolded_services


@app.delete("/services/{service_id}", status_code=204)
async def delete_service(service_id: str):
    for i, s in enumerate(scaffolded_services):
        if s["service_id"] == service_id:
            scaffolded_services.pop(i)
            return
    raise HTTPException(status_code=404, detail="Service not found")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
