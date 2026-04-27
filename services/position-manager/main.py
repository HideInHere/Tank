import os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "position-manager")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8016"))
DB_NAME = os.getenv("DB_NAME", "ledger")
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
positions: list[dict] = []


class PositionCreate(BaseModel):
    symbol: str
    quantity: float
    entry_price: float
    side: str  # "long" | "short"


class PositionUpdate(BaseModel):
    current_price: float


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


@app.get("/positions")
async def list_positions():
    return positions


@app.post("/positions", status_code=201)
async def create_position(req: PositionCreate):
    position = {
        "position_id": str(uuid.uuid4()),
        "symbol": req.symbol,
        "quantity": req.quantity,
        "entry_price": req.entry_price,
        "current_price": req.entry_price,
        "side": req.side,
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    positions.append(position)
    return position


@app.get("/positions/{position_id}")
async def get_position(position_id: str):
    for p in positions:
        if p["position_id"] == position_id:
            return p
    raise HTTPException(status_code=404, detail="Position not found")


@app.put("/positions/{position_id}")
async def update_position(position_id: str, req: PositionUpdate):
    for p in positions:
        if p["position_id"] == position_id:
            p["current_price"] = req.current_price
            if p["side"] == "long":
                p["pnl"] = round((req.current_price - p["entry_price"]) * p["quantity"], 4)
            else:
                p["pnl"] = round((p["entry_price"] - req.current_price) * p["quantity"], 4)
            if p["entry_price"] != 0:
                p["pnl_pct"] = round(p["pnl"] / (p["entry_price"] * p["quantity"]) * 100, 4)
            return p
    raise HTTPException(status_code=404, detail="Position not found")


@app.delete("/positions/{position_id}")
async def close_position(position_id: str):
    for i, p in enumerate(positions):
        if p["position_id"] == position_id:
            closed = positions.pop(i)
            return {"position_id": position_id, "final_pnl": closed["pnl"],
                    "symbol": closed["symbol"], "status": "closed"}
    raise HTTPException(status_code=404, detail="Position not found")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
