import asyncio, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "backtest-runner")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8019"))
DB_NAME = os.getenv("DB_NAME", "research")
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
backtests = []

class BacktestCreate(BaseModel):
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 100000.0

async def run_backtest(backtest_id: str, initial_capital: float):
    await asyncio.sleep(3)
    for b in backtests:
        if b["backtest_id"] == backtest_id:
            b["status"] = "completed"
            b["results"] = {
                "final_value": initial_capital * 1.28,
                "sharpe": 1.42,
                "max_drawdown": -0.12,
                "win_rate": 0.58,
                "total_trades": 134,
                "status": "completed",
            }
            break

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

@app.post("/backtests")
async def create_backtest(body: BacktestCreate):
    bt = {
        "backtest_id": str(uuid.uuid4()),
        "strategy": body.strategy,
        "symbol": body.symbol,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "initial_capital": body.initial_capital,
        "status": "running",
        "results": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    backtests.append(bt)
    asyncio.create_task(run_backtest(bt["backtest_id"], body.initial_capital))
    return bt

@app.get("/backtests")
async def list_backtests():
    return backtests

@app.get("/backtests/{backtest_id}")
async def get_backtest(backtest_id: str):
    for b in backtests:
        if b["backtest_id"] == backtest_id:
            return b
    raise HTTPException(status_code=404, detail="Backtest not found")

@app.get("/backtests/{backtest_id}/results")
async def get_backtest_results(backtest_id: str):
    for b in backtests:
        if b["backtest_id"] == backtest_id:
            if b["status"] == "completed":
                return b["results"]
            return JSONResponse(status_code=202, content={"status": b["status"], "backtest_id": backtest_id})
    raise HTTPException(status_code=404, detail="Backtest not found")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
