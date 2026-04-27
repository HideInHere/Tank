import asyncio, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "strategy-optimizer")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8020"))
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

strategies = {
    "strat-001": {"name": "momentum_cross", "params": {"fast": 10, "slow": 50}, "score": 1.42, "runs": 12},
    "strat-002": {"name": "mean_reversion", "params": {"window": 20, "threshold": 2.0}, "score": 1.18, "runs": 8},
    "strat-003": {"name": "breakout_trend", "params": {"period": 30, "atr_mult": 2.5}, "score": 1.61, "runs": 15},
}
optimization_runs = []

class OptimizeRequest(BaseModel):
    strategy_name: str
    param_space: dict
    objective: str = "sharpe"

class TuneRequest(BaseModel):
    params: dict

async def complete_optimization(run_id: str):
    await asyncio.sleep(2)
    for r in optimization_runs:
        if r["run_id"] == run_id:
            r["status"] = "completed"
            r["best_params"] = {"fast": 12, "slow": 48, "threshold": 1.8}
            r["best_score"] = 1.67
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

@app.get("/strategies")
async def list_strategies():
    return [{"strategy_id": k, **v} for k, v in strategies.items()]

@app.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    if strategy_id not in strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"strategy_id": strategy_id, **strategies[strategy_id]}

@app.post("/optimize")
async def optimize(body: OptimizeRequest):
    run = {
        "run_id": str(uuid.uuid4()),
        "strategy_name": body.strategy_name,
        "param_space": body.param_space,
        "objective": body.objective,
        "status": "running",
        "best_params": None,
        "best_score": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    optimization_runs.append(run)
    asyncio.create_task(complete_optimization(run["run_id"]))
    return run

@app.post("/strategies/{strategy_id}/tune")
async def tune_strategy(strategy_id: str, body: TuneRequest):
    if strategy_id not in strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategies[strategy_id]["params"].update(body.params)
    strategies[strategy_id]["runs"] += 1
    return {"tuned": True, "strategy_id": strategy_id, "params_updated": list(body.params.keys())}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
