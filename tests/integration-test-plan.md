# Integration Test Plan — Banks Agent + Swarm Orchestrator

## Overview

This document defines the integration tests for Banks Agent + Swarm Orchestrator microservices. **Tests are NOT RUN until approved.** This defines what will be tested, why, and how they help.

---

## Test Architecture

```
Banks Agent (:5694)
    ↓ (HTTP POST /prompt)
Swarm Orchestrator (:5696)
    ↓ (CLI: ruflo swarm start)
Ruflo Swarm
    ↓ (hive-mind spawn --claude)
Claude Code Workers (parallel execution)
    ↓ (results)
Swarm DB (swarm_db)
    ↓ (status updates)
Banks Agent
    ↓ (responses)
Telegram
```

---

## Test Categories

### 1. **Banks Agent Tests** (tests/integration/test_banks_agent.py)

#### 1.1 Health Check
- **What:** GET `/health` should return 200 with status="healthy"
- **Why:** Ensures Banks is running and database connected
- **How:** Simple HTTP GET, check response code + JSON fields
- **Dependencies:** banks-agent container, postgres-banks running

#### 1.2 Prompt Submission
- **What:** POST `/prompt` with high-level objective should return prompt_id + status
- **Why:** Banks must accept prompts and track them
- **How:** Submit `{"prompt": "Build momentum trading strategy", "priority": "high"}`, verify response has prompt_id
- **Dependencies:** Banks agent, postgres-banks, redis

#### 1.3 Prompt History
- **What:** GET `/prompts` should list all submitted prompts with status
- **Why:** Banks must persist and retrieve prompt history
- **How:** Submit multiple prompts, GET `/prompts`, verify all are returned with correct status
- **Dependencies:** Same as 1.2

#### 1.4 Swarm Listing
- **What:** GET `/swarms` should list all active swarms created by Banks
- **Why:** Banks must track which swarms it spawned
- **How:** Create swarm, GET `/swarms`, verify it appears in list
- **Dependencies:** Banks agent, Swarm Orchestrator, swarm_db

#### 1.5 Swarm Creation
- **What:** POST `/swarm/create` should create a new swarm via Swarm Orchestrator
- **Why:** Banks must be able to delegate to Swarm Orchestrator
- **How:** POST swarm creation request, verify swarm_id returned + status="initializing"
- **Dependencies:** Banks agent, Swarm Orchestrator, both DBs

---

### 2. **Swarm Orchestrator Tests** (tests/integration/test_swarm_orchestrator.py)

#### 2.1 Health Check
- **What:** GET `/health` should return 200 with status="healthy"
- **Why:** Ensures Swarm Orchestrator is running
- **How:** Simple HTTP GET, check response
- **Dependencies:** swarm-orchestrator container, postgres-swarm running

#### 2.2 Swarm Initialization
- **What:** POST `/swarm/init` should create new Ruflo swarm
- **Why:** Swarm Orchestrator is the interface to Ruflo
- **How:** POST with objective + agent count, verify swarm_id returned
- **Dependencies:** Swarm Orchestrator, swarm_db, ruflo CLI available

#### 2.3 Task Creation
- **What:** POST `/swarm/{swarm_id}/task` should add task to swarm task queue
- **Why:** Tasks must be created and tracked before execution
- **How:** Create swarm, add task, verify task_id returned + status="pending"
- **Dependencies:** Swarm Orchestrator, swarm_db

#### 2.4 Swarm Execution
- **What:** POST `/swarm/{swarm_id}/execute` should start hive-mind + Claude Code workers
- **Why:** Swarm must actually execute tasks with parallel workers
- **How:** Create swarm + tasks, start execution, verify status="executing", background task monitoring starts
- **Dependencies:** Swarm Orchestrator, ruflo CLI, Claude Code available

#### 2.5 Status Polling
- **What:** GET `/swarm/{swarm_id}` should return current status + task progress
- **Why:** Banks must be able to monitor swarm progress
- **How:** Execute swarm, poll `/swarm/{swarm_id}` every 5s, verify status updates from pending→executing→completed
- **Dependencies:** Swarm Orchestrator, swarm_db, active swarm

#### 2.6 Active Swarms Listing
- **What:** GET `/swarms/active` should list only executing/initializing swarms
- **Why:** Swarm Orchestrator must filter by status
- **How:** Create multiple swarms with different statuses, GET `/swarms/active`, verify only active ones listed
- **Dependencies:** Swarm Orchestrator, swarm_db

#### 2.7 Task Status Retrieval
- **What:** GET `/tasks/{task_id}` should return task details + status
- **Why:** Banks needs to track individual task progress
- **How:** Create task, GET task details, verify all fields present (type, description, status, etc)
- **Dependencies:** Swarm Orchestrator, swarm_db

---

### 3. **Inter-Service Communication Tests** (tests/integration/test_communication.py)

#### 3.1 Banks → Swarm HTTP Connection
- **What:** Banks can HTTP POST to Swarm Orchestrator and receive responses
- **Why:** Services must be able to reach each other on Docker network
- **How:** Banks calls POST `/swarm/init` on Swarm, verify response received
- **Dependencies:** Both services, Docker network bridge, ports exposed

#### 3.2 Redis Message Passing
- **What:** Both services can publish/subscribe on Redis streams
- **Why:** Async message passing for real-time updates
- **How:** Banks publishes to `banks:prompt-updates`, Swarm subscribes, verify message delivered
- **Dependencies:** redis-orchestrator, both services connected

#### 3.3 Database Isolation
- **What:** Each service's DB is isolated (banks_db ≠ swarm_db)
- **Why:** Services shouldn't share data stores
- **How:** Query banks_db for prompts, query swarm_db for swarms, verify data is isolated
- **Dependencies:** postgres-banks, postgres-swarm, both DBs initialized

#### 3.4 Fallback/Retry Logic
- **What:** If Swarm Orchestrator is down, Banks should retry and eventually fail gracefully
- **Why:** Resilience
- **How:** Stop Swarm Orchestrator, Banks tries to create swarm, verify error returned (not crash)
- **Dependencies:** Both services, error handling

---

### 4. **End-to-End Flow Tests** (tests/integration/test_e2e_flow.py)

#### 4.1 Full Pipeline: Prompt → Swarm → Execution
- **What:** Complete flow from Banks receiving prompt to Swarm executing tasks
- **Why:** Validates entire system works together
- **How:**
  1. Submit prompt to Banks: `{"prompt": "Build new service", "priority": "high"}`
  2. Banks calls Swarm to create swarm
  3. Banks calls Swarm to add tasks
  4. Banks calls Swarm to execute
  5. Poll Swarm status until completed
  6. Verify swarm_db has execution history
  7. Verify banks_db has prompt with final status
- **Dependencies:** Both services, both DBs, ruflo CLI, Claude Code

#### 4.2 Parallel Task Execution
- **What:** Multiple tasks in same swarm execute in parallel (not sequential)
- **Why:** Swarm's main value is parallel execution
- **How:**
  1. Create swarm with 5 tasks
  2. Execute swarm
  3. Verify all 5 tasks start roughly simultaneously (timestamps within 5 seconds)
  4. Measure total execution time (should be ~task_duration, not 5×task_duration)
- **Dependencies:** Swarm Orchestrator, ruflo, Claude Code workers

#### 4.3 Error Handling
- **What:** If a task fails, swarm continues and reports failure
- **Why:** One failed task shouldn't crash entire swarm
- **How:**
  1. Create swarm with intentionally failing task
  2. Execute swarm
  3. Verify swarm completes with status="completed_with_errors"
  4. Verify failed task status="failed", other tasks status="completed"
- **Dependencies:** Swarm Orchestrator, swarm_db

#### 4.4 Large Workload (10 tasks, 8 workers)
- **What:** Swarm can handle large workloads with many tasks
- **Why:** Production-scale testing
- **How:**
  1. Create swarm with 10 tasks
  2. Spawn 8 Claude Code workers
  3. Execute swarm
  4. Monitor completion time and resource usage
  5. Verify all tasks complete without memory leaks or hangs
- **Dependencies:** All previous + resource monitoring

---

### 5. **Database Tests** (tests/integration/test_databases.py)

#### 5.1 Banks DB Schema
- **What:** banks_db has correct tables: prompts, swarms, audit_log
- **Why:** Data persistence requires correct schema
- **How:** Query information_schema, verify tables exist with correct columns
- **Dependencies:** postgres-banks, schema initialized

#### 5.2 Swarm DB Schema
- **What:** swarm_db has correct tables: swarms, tasks, agents, execution_log
- **Why:** Swarm state persistence
- **How:** Query information_schema, verify tables and columns
- **Dependencies:** postgres-swarm, schema initialized

#### 5.3 Data Integrity
- **What:** After swarm completes, data in both DBs is consistent
- **Why:** Cross-DB consistency check
- **How:**
  1. Execute full pipeline
  2. Query banks_db for prompt → get swarm_id
  3. Query swarm_db for swarm → verify same ID exists
  4. Verify task counts match between tables
- **Dependencies:** Both DBs, executed swarm

#### 5.4 Backup/Recovery
- **What:** If DBs crash, data can be recovered from backups
- **Why:** Data durability
- **How:** Take backup, corrupt DB, restore, verify all data present
- **Dependencies:** Both DBs, backup scripts

---

### 6. **Performance Tests** (tests/integration/test_performance.py)

#### 6.1 Prompt Submission Latency
- **What:** POST `/prompt` completes in <100ms
- **Why:** Banks must be responsive
- **How:** Submit prompt, measure response time
- **Dependencies:** Banks agent, postgres-banks

#### 6.2 Swarm Initialization Latency
- **What:** POST `/swarm/init` completes in <500ms
- **Why:** Swarm creation should be fast
- **How:** Init swarm, measure response time
- **Dependencies:** Swarm Orchestrator, swarm_db, ruflo CLI

#### 6.3 Status Polling Latency
- **What:** GET `/swarm/{swarm_id}` completes in <100ms
- **Why:** Status checks must be responsive
- **How:** Poll status 100 times, measure average latency
- **Dependencies:** Swarm Orchestrator, swarm_db, active swarm

#### 6.4 Throughput: N Concurrent Prompts
- **What:** Banks can handle 10 concurrent prompt submissions
- **Why:** Production load testing
- **How:** Submit 10 prompts in parallel, verify all succeed
- **Dependencies:** Banks agent, postgres-banks, redis

---

## Test Execution Plan

### Phase 1: Unit (not included in this plan)
- Test each endpoint individually

### Phase 2: Integration (this plan)
- Test service-to-service communication
- Test database operations
- Test inter-service workflows

### Phase 3: End-to-End (E2E)
- Full system from prompt submission to swarm completion
- Simulate real trading system usage

### Phase 4: Performance
- Load testing
- Stress testing
- Latency profiling

---

## How Tests Help

### 1. **Validate Architecture**
- Tests ensure services communicate correctly over HTTP + Redis
- Tests verify databases are isolated and data flows correctly
- Tests confirm Swarm Orchestrator can drive Ruflo + Claude Code

### 2. **Catch Integration Bugs**
- Tests catch bugs where services fail to communicate (e.g., wrong endpoint, missing headers)
- Tests catch database schema mismatches
- Tests catch race conditions in parallel execution

### 3. **Ensure Reliability**
- Tests verify services recover from failures (e.g., Swarm down → Banks retries)
- Tests verify no data loss on failures
- Tests verify swarms complete despite individual task failures

### 4. **Measure Performance**
- Tests establish baseline latencies (should be <100ms for most operations)
- Tests ensure parallel execution actually saves time (not sequential)
- Tests verify large workloads don't cause memory leaks or hangs

### 5. **Document Behavior**
- Tests serve as executable documentation of how services should work
- Tests make it clear what "successful" execution looks like
- Tests help onboard new developers

---

## Test Infrastructure

### Test Database Setup
```bash
# Create test databases (isolated from production)
createdb banks_test
createdb swarm_test

# Initialize schemas
psql -U postgres -d banks_test < db/init-banks.sql
psql -U postgres -d swarm_test < db/init-swarm.sql
```

### Test Fixtures
```python
@pytest.fixture
def banks_client():
    """HTTP client for Banks agent"""
    return TestClient(banks_app)

@pytest.fixture
def swarm_client():
    """HTTP client for Swarm orchestrator"""
    return TestClient(swarm_app)

@pytest.fixture
def test_db():
    """Clean database for each test"""
    # Create transaction, rollback after test
    # Ensures tests don't interfere with each other
```

### Test Utilities
```python
def wait_for_swarm_completion(swarm_id, timeout=60):
    """Poll swarm status until completion"""
    start = time.time()
    while time.time() - start < timeout:
        status = swarm_client.get(f"/swarm/{swarm_id}")
        if status['status'] in ('completed', 'completed_with_errors'):
            return status
        time.sleep(1)
    raise TimeoutError(f"Swarm {swarm_id} did not complete")
```

---

## Success Criteria

All tests pass:
- ✅ Banks agent health check passes
- ✅ Prompts can be submitted and retrieved
- ✅ Swarm initialization succeeds
- ✅ Tasks can be added to swarms
- ✅ Swarms execute with parallel workers
- ✅ Status polling returns accurate progress
- ✅ Both DBs maintain consistency
- ✅ Services recover gracefully from failures
- ✅ Parallel execution is actually faster than sequential
- ✅ No data loss on any failure scenario
- ✅ All latencies are within acceptable bounds (<100ms for most operations)

When all tests pass, the system is ready for:
1. Code review
2. GitHub push
3. Deployment to Mac
4. Integration with full trading system

---

## Next Steps

1. **Approve test plan** — Ensure tests cover all critical paths
2. **Implement test fixtures** — Set up test databases and utilities
3. **Write tests** — Implement tests from this plan
4. **Run tests** — Execute full test suite
5. **Fix failures** — Debug and fix any issues
6. **Push to GitHub** — Commit tests + code
7. **Deploy to Mac** — Run system end-to-end
