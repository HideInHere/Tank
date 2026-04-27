#!/usr/bin/env python3
"""Signal Generator - Generate trading signals from market data"""

from fastapi import FastAPI
from datetime import datetime
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Signal Generator", version="1.0.0")

DB_CONFIG = {'host': 'postgres-signals', 'database': 'signals_db', 'user': 'postgres', 'password': 'postgres', 'port': 5432}

@app.get('/health')
async def health():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return {'status': 'healthy', 'service': 'signal-generator', 'timestamp': datetime.utcnow().isoformat()}
    except:
        return {'status': 'unhealthy'}, 503

@app.get('/signals')
async def get_signals():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT 100")
        signals = cursor.fetchall()
        conn.close()
        return {'signals': signals, 'count': len(signals)}
    except Exception as e:
        return {'error': str(e)}, 500

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8032)
