import asyncio, os, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn, redis.asyncio as aioredis, psycopg2
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
import structlog

SERVICE_NAME = os.getenv("SERVICE_NAME", "report-generator")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8018"))
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
reports = []

class ReportCreate(BaseModel):
    report_type: str
    params: dict

async def process_report(report_id: str):
    await asyncio.sleep(2)
    for r in reports:
        if r["report_id"] == report_id:
            r["status"] = "completed"
            r["completed_at"] = datetime.now(timezone.utc).isoformat()
            r["data"] = {"sharpe": 1.35, "return": 0.28, "trades": 89}
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

@app.post("/reports")
async def create_report(body: ReportCreate):
    if body.report_type not in ("backtest", "live", "risk", "performance"):
        raise HTTPException(status_code=400, detail="Invalid report_type")
    report = {
        "report_id": str(uuid.uuid4()),
        "report_type": body.report_type,
        "params": body.params,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "data": None,
    }
    reports.append(report)
    asyncio.create_task(process_report(report["report_id"]))
    return report

@app.get("/reports")
async def list_reports():
    return reports

@app.get("/reports/{report_id}")
async def get_report(report_id: str):
    for r in reports:
        if r["report_id"] == report_id:
            return r
    raise HTTPException(status_code=404, detail="Report not found")

@app.get("/reports/{report_id}/download")
async def download_report(report_id: str):
    for r in reports:
        if r["report_id"] == report_id:
            if r["status"] == "completed":
                return JSONResponse(content=r["data"])
            return JSONResponse(status_code=202, content={"status": "processing", "report_id": report_id})
    raise HTTPException(status_code=404, detail="Report not found")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
