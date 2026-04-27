#!/usr/bin/env python3
"""Banks Agent — High-level prompt orchestration with Sonnet

Banks is a specialized agent that:
1. Takes high-level project prompts (e.g. "build a new trading strategy")
2. Uses Claude Sonnet to break down into architecture + implementation steps
3. Spawns task swarms for actual execution
4. Monitors progress and reports status
5. Never touches code directly - only coordinates via swarm

Communication: Redis Streams for inter-service messaging
Database: banks_db for agent state, task history, decision logs
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Banks Agent",
    description="High-level prompt orchestration with Claude Sonnet",
    version="1.0.0"
)

# Database
DB_CONFIG = {
    'host': 'postgres-banks',
    'database': 'banks_db',
    'user': 'postgres',
    'password': 'postgres',
    'port': 5432
}

# Redis for inter-service communication
redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

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
            'service': 'banks-agent',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {'status': 'unhealthy', 'error': str(e)}, 503

@app.post('/prompt')
async def process_prompt(data: Dict[str, Any]):
    """
    Accept high-level prompt, break into tasks via Sonnet, create swarm
    
    Input:
    {
        "prompt": "Build new trading strategy for momentum trading",
        "priority": "high",
        "deadline": "2026-04-30T08:00:00Z"
    }
    
    Output:
    {
        "prompt_id": "PROMPT001",
        "status": "analyzing",
        "tasks": [...],
        "swarm_id": "swarm-xxxxx"
    }
    """
    try:
        prompt = data.get('prompt')
        priority = data.get('priority', 'normal')
        deadline = data.get('deadline')
        
        logger.info(f"Processing prompt: {prompt[:100]}...")
        
        # Store in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO prompts (content, priority, deadline, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (prompt, priority, deadline, 'received')
        )
        prompt_id = cursor.fetchone()[0]
        conn.commit()
        
        # TODO: Call Sonnet to break down prompt into tasks
        # For now, return placeholder
        
        return {
            'prompt_id': f"PROMPT{prompt_id:04d}",
            'status': 'analyzing',
            'message': 'Prompt received. Sonnet is analyzing...',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Prompt processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get('/prompts')
async def get_prompts():
    """List all prompts and their status"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM prompts ORDER BY ts DESC LIMIT 50")
        prompts = cursor.fetchall()
        conn.close()
        
        return {
            'prompts': [dict(p) for p in prompts],
            'count': len(prompts)
        }
    except Exception as e:
        logger.error(f"Failed to fetch prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/swarms')
async def get_swarms():
    """List all active swarms spawned by Banks"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM swarms WHERE status != 'completed' ORDER BY ts DESC LIMIT 20")
        swarms = cursor.fetchall()
        conn.close()
        
        return {
            'swarms': [dict(s) for s in swarms],
            'count': len(swarms)
        }
    except Exception as e:
        logger.error(f"Failed to fetch swarms: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/swarm/create')
async def create_swarm(data: Dict[str, Any]):
    """Create a new Ruflo swarm for task execution"""
    try:
        prompt_id = data.get('prompt_id')
        tasks = data.get('tasks', [])
        priority = data.get('priority', 'normal')
        
        logger.info(f"Creating swarm for prompt {prompt_id} with {len(tasks)} tasks")
        
        # Store in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO swarms (prompt_id, task_count, priority, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (prompt_id, len(tasks), priority, 'initializing')
        )
        swarm_id = cursor.fetchone()[0]
        conn.commit()
        
        # TODO: Actually spawn ruflo swarm via CLI
        # For now, return placeholder
        
        return {
            'swarm_id': f"swarm-{swarm_id:06d}",
            'status': 'initializing',
            'task_count': len(tasks),
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Swarm creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.websocket("/ws/prompts")
async def websocket_prompts(websocket: WebSocket):
    """WebSocket for real-time prompt status updates"""
    await websocket.accept()
    try:
        while True:
            # Listen for prompt updates on Redis
            message = redis_client.blpop('banks:prompt-updates', timeout=5)
            if message:
                _, data = message
                await websocket.send_text(data)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == '__main__':
    logger.info("Starting Banks Agent on :5694")
    uvicorn.run(app, host='0.0.0.0', port=5694)
