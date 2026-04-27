import os, time, logging, asyncio
from contextlib import asynccontextmanager
import psycopg2
import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import httpx, uvicorn
from tenacity import retry, stop_after_attempt, wait_fixed

SERVICE_NAME = os.getenv("SERVICE_NAME", "monitor")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8007"))
DB_NAME = os.getenv("DB_NAME", "tank")
PG_HOST = os.getenv("POSTGRES_HOST", "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_USER = os.getenv("POSTGRES_USER", "tank")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "")
START_TIME = time.time()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(SERVICE_NAME)
REQ = Counter("http_requests_total", "Requests", ["method", "path", "status"])
INIT_SQL = "SELECT 1"

SERVICES = {
    "api-proxy": "http://api-proxy:8001",
    "research": "http://research:8002",
    "decision": "http://decision:8003",
    "executor": "http://executor:8004",
    "ledger": "http://ledger:8005",
    "tournament": "http://tournament:8006",
    "memory-sync": "http://memory-sync:8008",
    "banks-service": "http://banks-service:8009",
    "meta-builder": "http://meta-builder:8010",
    "risk-manager": "http://risk-manager:8011",
    "portfolio-tracker": "http://portfolio-tracker:8012",
    "market-data": "http://market-data:8013",
    "signal-generator": "http://signal-generator:8014",
    "order-router": "http://order-router:8015",
    "position-manager": "http://position-manager:8016",
    "alert-service": "http://alert-service:8017",
    "report-generator": "http://report-generator:8018",
    "backtest-runner": "http://backtest-runner:8019",
    "strategy-optimizer": "http://strategy-optimizer:8020",
    "feed-aggregator": "http://feed-aggregator:8021",
    "auth-service": "http://auth-service:8022",
    "notification-service": "http://notification-service:8023",
    "analytics-service": "http://analytics-service:8024",
    "openclaw-gateway": "http://openclaw-gateway:18789",
    "tank-agent": "http://tank-agent:9000",
}

service_health: dict = {}
db = None
r = None


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def connect_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASS, dbname=DB_NAME, connect_timeout=5,
    )


async def poll_services():
    while True:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for name, base_url in SERVICES.items():
                try:
                    resp = await client.get(f"{base_url}/health")
                    data = resp.json() if resp.status_code == 200 else {}
                    status = "healthy" if resp.status_code == 200 else "degraded"
                except Exception as e:
                    status = "unreachable"
                    data = {"error": str(e)}
                entry = {"status": status, "ts": int(time.time()), "data": data}
                service_health[name] = entry
                if r:
                    try:
                        import json
                        r.setex(f"monitor:health:{name}", 120, json.dumps(entry))
                    except Exception:
                        pass
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app):
    global db, r
    try:
        db = connect_db()
        with db.cursor() as cur:
            cur.execute(INIT_SQL)
        db.commit()
        logger.info("DB connected: %s", DB_NAME)
    except Exception as e:
        logger.warning("DB error: %s", e)
    try:
        r = redis_lib.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS,
            decode_responses=True, socket_connect_timeout=3,
        )
        r.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis error: %s", e)
    task = asyncio.create_task(poll_services())
    yield
    task.cancel()
    if db and not db.closed:
        db.close()


app = FastAPI(title=SERVICE_NAME, version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health():
    db_ok = bool(db and not db.closed)
    try:
        r_ok = bool(r and r.ping())
    except Exception:
        r_ok = False
    return {
        "status": "healthy", "service": SERVICE_NAME,
        "db": db_ok, "redis": r_ok,
        "uptime": round(time.time() - START_TIME),
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/status")
def aggregate_status():
    REQ.labels("GET", "/status", "200").inc()
    total = len(SERVICES)
    healthy = sum(1 for v in service_health.values() if v.get("status") == "healthy")
    degraded = sum(1 for v in service_health.values() if v.get("status") == "degraded")
    return {
        "total": total,
        "healthy": healthy,
        "degraded": degraded,
        "unreachable": total - healthy - degraded,
        "services": {k: {"status": v.get("status"), "ts": v.get("ts")} for k, v in service_health.items()},
    }


@app.get("/services")
def list_services():
    REQ.labels("GET", "/services", "200").inc()
    result = []
    for name, base_url in SERVICES.items():
        entry = service_health.get(name, {"status": "unknown", "ts": None, "data": {}})
        result.append({"name": name, "url": base_url, **entry})
    return {"services": result, "count": len(result)}


@app.get("/services/{name}")
def get_service_health(name: str):
    REQ.labels("GET", "/services/{name}", "200").inc()
    if name not in SERVICES:
        raise HTTPException(404, "Service not found")
    entry = service_health.get(name, {"status": "unknown", "ts": None, "data": {}})
    return {"name": name, "url": SERVICES[name], **entry}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT)
