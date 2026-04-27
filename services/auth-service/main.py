import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "auth-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8022"))
DB_NAME = os.getenv("DB_NAME", "tank")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
JWT_SECRET = os.getenv("JWT_SECRET", "changeme-secret")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])

redis_client = None
db_conn = None
api_keys = {}

class KeyCreate(BaseModel):
    name: str
    permissions: list[str] = ["read"]

class VerifyRequest(BaseModel):
    api_key: str

class LoginRequest(BaseModel):
    username: str
    password: str

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

@app.post("/keys")
async def create_key(body: KeyCreate):
    key_id = str(uuid.uuid4())
    key_value = uuid.uuid4().hex
    record = {
        "key_id": key_id,
        "key_value": key_value,
        "name": body.name,
        "permissions": body.permissions,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    api_keys[key_id] = record
    return record

@app.get("/keys")
async def list_keys():
    return [
        {k: v for k, v in entry.items() if k != "key_value"}
        for entry in api_keys.values()
    ]

@app.delete("/keys/{key_id}")
async def deactivate_key(key_id: str):
    if key_id not in api_keys:
        raise HTTPException(status_code=404, detail="Key not found")
    api_keys[key_id]["active"] = False
    return {"deactivated": True, "key_id": key_id}

@app.post("/verify")
async def verify_key(body: VerifyRequest):
    for key_id, entry in api_keys.items():
        if entry["key_value"] == body.api_key and entry["active"]:
            return {"valid": True, "key_id": key_id, "permissions": entry["permissions"]}
    return {"valid": False, "key_id": None, "permissions": []}

@app.post("/login")
async def login(body: LoginRequest):
    if body.username == "admin" and body.password == JWT_SECRET[:8]:
        return {"token": uuid.uuid4().hex, "expires_in": 3600}
    raise HTTPException(status_code=401, detail="Invalid credentials")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
