#!/usr/bin/env python3
"""Alert Service - Real-time alerts and notifications"""

from fastapi import FastAPI
from datetime import datetime
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alert Service", version="1.0.0")

DB_CONFIG = {'host': 'postgres-alerts', 'database': 'alerts_db', 'user': 'postgres', 'password': 'postgres', 'port': 5432}

@app.get('/health')
async def health():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return {'status': 'healthy', 'service': 'alert-service', 'timestamp': datetime.utcnow().isoformat()}
    except:
        return {'status': 'unhealthy'}, 503

@app.get('/alerts')
async def get_alerts():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 100")
        alerts = cursor.fetchall()
        conn.close()
        return {'alerts': alerts, 'count': len(alerts)}
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8027)
