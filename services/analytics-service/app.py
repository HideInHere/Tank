#!/usr/bin/env python3
"""Analytics Service - Real-time analytics and KPI tracking"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram
import psycopg2
from psycopg2.extras import RealDictCursor
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="Analytics Service",
    description="Real-time analytics and KPI tracking",
    version="1.0.0"
)

# Prometheus metrics
analytics_requests = Counter('analytics_requests_total', 'Total analytics requests')
analytics_latency = Histogram('analytics_latency_ms', 'Analytics request latency')
active_metrics = Gauge('active_metrics_count', 'Number of active metrics')

# Database
DB_CONFIG = {
    'host': 'postgres-analytics',
    'database': 'analytics_db',
    'user': 'postgres',
    'password': 'postgres',
    'port': 5432
}

def get_db():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

@app.get('/health')
async def health():
    """Health check endpoint"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return {
            'status': 'healthy',
            'service': 'analytics-service',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {'status': 'unhealthy', 'error': str(e)}, 503

@app.get('/metrics')
async def get_metrics():
    """Get current metrics"""
    analytics_requests.inc()
    
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM metrics LIMIT 100")
        metrics = cursor.fetchall()
        conn.close()
        
        active_metrics.set(len(metrics))
        return {
            'metrics': [dict(m) for m in metrics],
            'count': len(metrics),
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/metrics/record')
async def record_metric(data: Dict[str, Any]):
    """Record a new metric"""
    analytics_requests.inc()
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO metrics (name, value, tags, ts)
            VALUES (%s, %s, %s, NOW())
            """,
            (data.get('name'), data.get('value'), data.get('tags'))
        )
        conn.commit()
        conn.close()
        
        return {'status': 'recorded', 'metric': data}
    except Exception as e:
        logger.error(f"Failed to record metric: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/kpis')
async def get_kpis():
    """Get key performance indicators"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM kpis ORDER BY ts DESC LIMIT 20")
        kpis = cursor.fetchall()
        conn.close()
        
        return {
            'kpis': [dict(k) for k in kpis],
            'count': len(kpis)
        }
    except Exception as e:
        logger.error(f"Failed to fetch KPIs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    logger.info("Starting Analytics Service on :8024")
    uvicorn.run(app, host='0.0.0.0', port=8024)
