#!/usr/bin/env python3
"""Portfolio Tracker - Real-time portfolio position tracking"""

from fastapi import FastAPI
from datetime import datetime
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Portfolio Tracker", version="1.0.0")

DB_CONFIG = {'host': 'postgres-portfolio', 'database': 'portfolio_db', 'user': 'postgres', 'password': 'postgres', 'port': 5432}

@app.get('/health')
async def health():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return {'status': 'healthy', 'service': 'portfolio-tracker', 'timestamp': datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {'status': 'unhealthy', 'error': str(e)}, 503

@app.get('/portfolio')
async def get_portfolio():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions LIMIT 100")
        positions = cursor.fetchall()
        conn.close()
        return {'positions': positions, 'count': len(positions)}
    except Exception as e:
        logger.error(f"Failed to fetch portfolio: {e}")
        return {'error': str(e)}, 500

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8025)
