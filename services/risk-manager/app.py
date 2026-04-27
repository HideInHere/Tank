#!/usr/bin/env python3
"""Risk Manager - Portfolio risk assessment and limits"""

from fastapi import FastAPI
from datetime import datetime
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Risk Manager", version="1.0.0")

DB_CONFIG = {'host': 'postgres-risk', 'database': 'risk_db', 'user': 'postgres', 'password': 'postgres', 'port': 5432}

@app.get('/health')
async def health():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return {'status': 'healthy', 'service': 'risk-manager', 'timestamp': datetime.utcnow().isoformat()}
    except:
        return {'status': 'unhealthy'}, 503

@app.get('/risk-metrics')
async def get_risk_metrics():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM risk_metrics ORDER BY ts DESC LIMIT 50")
        metrics = cursor.fetchall()
        conn.close()
        return {'metrics': metrics, 'count': len(metrics)}
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8026)
