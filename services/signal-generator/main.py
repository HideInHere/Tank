import os, uuid, random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "signal-generator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8014"))
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

redis_client = None
db_conn = None

SIGNAL_TYPES = ["momentum", "mean_reversion", "sentiment"]
DEFAULT_SYMBOLS = ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN"]


def make_signal(symbol: str) -> dict:
    return {
        "signal_id": str(uuid.uuid4()),
        "symbol": symbol,
        "type": random.choice(SIGNAL_TYPES),
        "direction": random.choice(["long", "short"]),
        "strength": round(random.uniform(0.4, 0.99), 4),
        "alpha": round(random.uniform(-0.05, 0.15), 6),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class GenerateRequest(BaseModel):
    symbols: list[str]
    strategy: str


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


@app.get("/signals")
async def list_signals():
    return [make_signal(sym) for sym in DEFAULT_SYMBOLS]


@app.get("/signals/{symbol}")
async def get_signals_for_symbol(symbol: str):
    return [make_signal(symbol.upper()) for _ in range(3)]


@app.post("/signals/generate")
async def generate_signals(req: GenerateRequest):
    signals = [make_signal(sym.upper()) for sym in req.symbols]
    if redis_client:
        for sig in signals:
            await redis_client.xadd("stream:signals", {
                "signal_id": sig["signal_id"], "symbol": sig["symbol"],
                "type": sig["type"], "direction": sig["direction"],
                "strength": str(sig["strength"]), "alpha": str(sig["alpha"]),
                "generated_at": sig["generated_at"],
            })
    return signals


@app.get("/alpha")
async def get_alpha():
    return {"momentum": 0.67, "mean_reversion": 0.45, "sentiment": 0.72, "combined": 0.61}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
