import os
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import redis.asyncio as aioredis
import psycopg2
import structlog
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SERVICE_NAME = os.getenv("SERVICE_NAME", "decision")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8003"))
DB_NAME = os.getenv("DB_NAME", "decision")
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
votes_store: list = []

class VoteRequest(BaseModel):
    symbol: str
    signal: str
    confidence: float
    source: str

class StrategyEvalRequest(BaseModel):
    strategy_name: str
    params: dict

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

@app.post("/vote")
async def cast_vote(req: VoteRequest):
    vote_id = str(uuid.uuid4())
    votes_store.append({"vote_id": vote_id, "symbol": req.symbol, "signal": req.signal, "confidence": req.confidence, "source": req.source})
    return {"vote_id": vote_id, "accepted": True}

@app.get("/consensus")
async def get_consensus():
    tally: dict = defaultdict(lambda: defaultdict(list))
    for v in votes_store:
        tally[v["symbol"]][v["signal"]].append(v["confidence"])
    result = {}
    for symbol, signals in tally.items():
        best_signal = max(signals, key=lambda s: sum(signals[s]) / len(signals[s]))
        avg_conf = sum(signals[best_signal]) / len(signals[best_signal])
        result[symbol] = {"action": best_signal, "confidence": round(avg_conf, 3), "votes": sum(len(v) for v in signals.values())}
    return result

@app.get("/decision/{symbol}")
async def get_decision(symbol: str):
    sym_votes = [v for v in votes_store if v["symbol"] == symbol.upper()]
    if not sym_votes:
        return {"symbol": symbol.upper(), "action": "hold", "confidence": 0.5, "votes": 0, "unanimous": False}
    tally: dict = defaultdict(list)
    for v in sym_votes:
        tally[v["signal"]].append(v["confidence"])
    best = max(tally, key=lambda s: sum(tally[s]) / len(tally[s]))
    avg_conf = sum(tally[best]) / len(tally[best])
    return {"symbol": symbol.upper(), "action": best, "confidence": round(avg_conf, 3), "votes": len(sym_votes), "unanimous": len(tally) == 1}

@app.post("/strategy/evaluate")
async def evaluate_strategy(req: StrategyEvalRequest):
    return {"strategy_name": req.strategy_name, "score": 0.78, "risk_adjusted": 0.65, "recommended": True}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
