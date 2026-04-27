#!/usr/bin/env python3
"""Auth Service - Authentication and authorization"""

from fastapi import FastAPI
from datetime import datetime
import psycopg2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Auth Service", version="1.0.0")

DB_CONFIG = {'host': 'postgres-auth', 'database': 'auth_db', 'user': 'postgres', 'password': 'postgres', 'port': 5432}

@app.get('/health')
async def health():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.close()
        return {'status': 'healthy', 'service': 'auth-service', 'timestamp': datetime.utcnow().isoformat()}
    except:
        return {'status': 'unhealthy'}, 503

@app.post('/authenticate')
async def authenticate(data: dict):
    return {'token': 'jwt_token_here', 'user': data}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8029)
