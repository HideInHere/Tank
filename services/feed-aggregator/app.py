#!/usr/bin/env python3
"""Feed Aggregator - Aggregate market data from multiple sources"""

from fastapi import FastAPI
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Feed Aggregator", version="1.0.0")

@app.get('/health')
async def health():
    return {'status': 'healthy', 'service': 'feed-aggregator', 'timestamp': datetime.utcnow().isoformat()}

@app.get('/feed')
async def get_feed():
    return {'status': 'ok', 'feed': 'market data stream'}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8033)
