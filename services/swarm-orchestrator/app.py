#!/usr/bin/env python3
"""Swarm Orchestrator — Ruflo swarm management and Claude Code execution

Swarm Orchestrator:
1. Manages Ruflo swarms (initialization, task creation, agent spawning)
2. Spawns Claude Code instances for parallel execution
3. Monitors task progress and agent status
4. Collects results and reports back to Banks
5. Stores execution history and learns from patterns

Communication: Redis for job queue + results, HTTP for status
Database: swarm_db for swarm state, task history, agent logs, execution metrics
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Swarm Orchestrator",
    description="Ruflo swarm management with Claude Code parallel execution",
    version="1.0.0"
)

# Database
DB_CONFIG = {
    'host': 'postgres-swarm',
    'database': 'swarm_db',
    'user': 'postgres',
    'password': 'postgres',
    'port': 5432
}

# Redis for job queuing
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
            'service': 'swarm-orchestrator',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {'status': 'unhealthy', 'error': str(e)}, 503

@app.post('/swarm/init')
async def init_swarm(data: Dict[str, Any]):
    """
    Initialize a new Ruflo swarm
    
    Input:
    {
        "objective": "Build new trading strategy...",
        "priority": "high",
        "agents": 8,
        "timeout": 3600
    }
    """
    try:
        objective = data.get('objective')
        priority = data.get('priority', 'normal')
        agents = data.get('agents', 8)
        timeout = data.get('timeout', 3600)
        
        logger.info(f"Initializing swarm: {objective[:100]}...")
        
        # Store in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO swarms (objective, priority, agent_count, timeout, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (objective, priority, agents, timeout, 'initializing')
        )
        swarm_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        # TODO: Call ruflo swarm start CLI
        swarm_name = f"swarm-{swarm_id:06d}"
        
        return {
            'swarm_id': swarm_name,
            'status': 'initializing',
            'agents': agents,
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Swarm init failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/swarm/{swarm_id}/task')
async def add_task(swarm_id: str, data: Dict[str, Any]):
    """
    Add a task to an existing swarm
    
    Input:
    {
        "type": "implementation",
        "description": "Build docker-compose.yml"
    }
    """
    try:
        task_type = data.get('type')
        description = data.get('description')
        priority = data.get('priority', 'normal')
        
        logger.info(f"Adding task to {swarm_id}: {description[:100]}...")
        
        # Store in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO tasks (swarm_id, type, description, priority, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (swarm_id, task_type, description, priority, 'pending')
        )
        task_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        # TODO: Call ruflo task create + assign
        
        return {
            'task_id': f"task-{task_id:06d}",
            'status': 'pending',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Task creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/swarm/{swarm_id}/execute')
async def execute_swarm(swarm_id: str, background_tasks: BackgroundTasks):
    """
    Start execution of swarm with hive-mind + Claude Code workers
    
    This spawns N parallel Claude Code instances to execute tasks
    """
    try:
        logger.info(f"Starting execution for {swarm_id} with hive-mind...")
        
        # TODO: Call ruflo hive-mind init + spawn --claude
        
        # Background task to monitor execution
        background_tasks.add_task(monitor_swarm_execution, swarm_id)
        
        return {
            'swarm_id': swarm_id,
            'status': 'executing',
            'message': 'Hive-mind spawned, Claude Code workers active',
            'timestamp': datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Swarm execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def monitor_swarm_execution(swarm_id: str):
    """Monitor swarm execution in background"""
    try:
        logger.info(f"Monitoring execution for {swarm_id}...")
        
        # Poll swarm status every 5 seconds
        for i in range(720):  # 1 hour max
            # TODO: Call ruflo swarm status
            # Check if completed
            # Update database with progress
            await asyncio.sleep(5)
            
            # Check if done
            # If done, collect results and notify Banks
            
    except Exception as e:
        logger.error(f"Monitor error for {swarm_id}: {e}")

@app.get('/swarm/{swarm_id}')
async def get_swarm_status(swarm_id: str):
    """Get current status of a swarm"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM swarms WHERE id = %s", (swarm_id,))
        swarm = cursor.fetchone()
        
        if not swarm:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Swarm {swarm_id} not found")
        
        # Get tasks
        cursor.execute("SELECT * FROM tasks WHERE swarm_id = %s", (swarm_id,))
        tasks = cursor.fetchall()
        
        # Get agents
        cursor.execute("SELECT * FROM agents WHERE swarm_id = %s", (swarm_id,))
        agents = cursor.fetchall()
        
        conn.close()
        
        return {
            'swarm': dict(swarm),
            'tasks': [dict(t) for t in tasks],
            'agents': [dict(a) for a in agents],
            'task_count': len(tasks),
            'agent_count': len(agents)
        }
    except Exception as e:
        logger.error(f"Failed to fetch swarm status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/swarms/active')
async def get_active_swarms():
    """Get all active swarms"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM swarms WHERE status IN ('initializing', 'executing') ORDER BY ts DESC LIMIT 20"
        )
        swarms = cursor.fetchall()
        conn.close()
        
        return {
            'swarms': [dict(s) for s in swarms],
            'count': len(swarms)
        }
    except Exception as e:
        logger.error(f"Failed to fetch active swarms: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/tasks/{task_id}')
async def get_task_status(task_id: str):
    """Get status of a specific task"""
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        task = cursor.fetchone()
        conn.close()
        
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return dict(task)
    except Exception as e:
        logger.error(f"Failed to fetch task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == '__main__':
    logger.info("Starting Swarm Orchestrator on :5696")
    uvicorn.run(app, host='0.0.0.0', port=5696)
