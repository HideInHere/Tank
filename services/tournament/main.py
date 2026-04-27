import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "tournament")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8006"))
DB_NAME = os.getenv("DB_NAME", "tournament")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_USER = os.getenv("POSTGRES_USER", "tank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

log = structlog.get_logger()
REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])

redis_client = None
db_conn = None

LEADERBOARD = [
    {"rank": 1, "strategy": "MomentumAlpha", "sharpe": 2.14, "total_return": 0.48, "max_drawdown": -0.08, "author": "trader_a"},
    {"rank": 2, "strategy": "MeanRevX",      "sharpe": 1.89, "total_return": 0.39, "max_drawdown": -0.11, "author": "trader_b"},
    {"rank": 3, "strategy": "TrendRider",    "sharpe": 1.61, "total_return": 0.31, "max_drawdown": -0.14, "author": "trader_c"},
    {"rank": 4, "strategy": "VolArb",        "sharpe": 1.42, "total_return": 0.26, "max_drawdown": -0.17, "author": "trader_d"},
    {"rank": 5, "strategy": "GridBot",       "sharpe": 1.21, "total_return": 0.19, "max_drawdown": -0.21, "author": "trader_e"},
]
submissions: list = []

class SubmitRequest(BaseModel):
    strategy_name: str
    code_hash: str
    author: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client, db_conn
    redis_client = await aioredis.from_url(
        f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}",
        encoding="utf-8", decode_responses=True
    )
    try:
        db_conn = psycopg2.connect(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=DB_NAME, user=POSTGRES_USER, password=POSTGRES_PASSWORD
        )
        log.info("db_connected", service=SERVICE_NAME, db=DB_NAME)
    except Exception as e:
        log.warning("db_connect_failed", error=str(e))
    log.info("service_started", service=SERVICE_NAME, port=SERVICE_PORT)
    yield
    if redis_client:
        await redis_client.aclose()
    if db_conn:
        db_conn.close()

app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "db": db_conn is not None and not db_conn.closed, "redis": redis_client is not None}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/tournament")
async def get_tournament():
    return {"id": "t-2026-w17", "week": "2026-W17", "status": "active", "participants": len(LEADERBOARD) + len(submissions), "ends_at": "2026-05-03T23:59:59Z"}

@app.get("/tournament/leaderboard")
async def get_leaderboard():
    return sorted(LEADERBOARD, key=lambda x: x["sharpe"], reverse=True)

@app.post("/tournament/submit")
async def submit_strategy(req: SubmitRequest):
    submission_id = str(uuid.uuid4())
    submissions.append({"submission_id": submission_id, "strategy_name": req.strategy_name, "code_hash": req.code_hash, "author": req.author, "status": "pending"})
    return {"submission_id": submission_id, "accepted": True, "rank": "pending"}

@app.get("/tournament/results")
async def get_results():
    return [
        {"week": "2026-W16", "winner": "MomentumAlpha", "sharpe": 2.05, "participants": 6, "ended_at": "2026-04-20T23:59:59Z"},
        {"week": "2026-W15", "winner": "TrendRider",    "sharpe": 1.97, "participants": 7, "ended_at": "2026-04-13T23:59:59Z"},
        {"week": "2026-W14", "winner": "GridBot",       "sharpe": 1.83, "participants": 5, "ended_at": "2026-04-06T23:59:59Z"},
    ]

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
