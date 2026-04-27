# SWARM — Ruflo Multi-Agent Orchestration Guide

## What is Swarm?

**Swarm** = Ruflo v3.5 enterprise AI orchestration platform that spawns **parallel Claude Code instances** to execute tasks efficiently, with minimal token cost and maximum throughput.

### Key Features
- **8-Agent Coordinated Execution** — 1 coordinator + 1 architect + 3 coders + 2 testers + 1 reviewer
- **Parallel Task Distribution** — All agents work simultaneously (3x faster than sequential)
- **Self-Learning Memory** — SONA (Self-Optimizing Neural Adaptation) learns from each task
- **Claude Code Integration** — Uses claude code workers for actual code execution
- **Hive-Mind Mode** — Queen coordinator routes tasks to best agent automatically
- **Token-Efficient** — Distributes work to minimize total tokens (Haiku for simple, Sonnet for complex)

---

## How Swarm Works (Step-by-Step)

### 1. Initialize Swarm
```bash
cd /path/to/project
ruflo swarm start --objective "Your high-level goal here"
```

**What happens:**
- Ruflo creates a swarm with 8 agent slots
- Coordinator is elected as "queen"
- Task queue is initialized
- MCP (Model Context Protocol) server starts

### 2. Create Subtasks
```bash
# Each subtask is a discrete unit of work
ruflo task create -t implementation -d "Build docker-compose.yml with 33 services"
ruflo task create -t implementation -d "Create all Dockerfiles"
ruflo task create -t testing -d "Write E2E tests"
ruflo task create -t testing -d "Run integration tests"
```

**Types:** implementation, testing, design, documentation, review, refactor, security, performance

### 3. Spawn Agents
```bash
# Let swarm auto-create optimal agents based on objective
ruflo swarm coordinate swarm-ID --start

# OR manually spawn specific agents
ruflo agent spawn -t architect --name my-architect --model sonnet
ruflo agent spawn -t coder --name coder-1 --model sonnet
ruflo agent spawn -t coder --name coder-2 --model sonnet
ruflo agent spawn -t tester --name tester-1 --model sonnet
```

### 4. Assign Tasks to Agents
```bash
# Assign tasks to agents (they execute immediately)
ruflo task assign task-1 --agent architect
ruflo task assign task-2 --agent coder-1
ruflo task assign task-3 --agent coder-2 &  # Run in parallel
ruflo task assign task-4 --agent tester-1 &
wait  # Wait for all to complete
```

**Key:** Use `&` to run assignments in parallel, `wait` to sync.

### 5. Enable Hive-Mind (Autonomous Execution)
```bash
# Initialize hive-mind (queen coordinator)
ruflo hive-mind init

# Spawn claude code workers to execute swarm tasks
ruflo hive-mind spawn --claude --swarm swarm-ID --workers 8
```

**What happens:**
- Queen coordinator is elected
- 8 Claude Code instances spawned in background
- Each worker picks up a task from the queue
- Agents execute in parallel
- Results are collected automatically

### 6. Monitor Progress
```bash
# Check overall swarm status
ruflo swarm status swarm-ID

# Watch agent activity
ruflo agent list

# Get task progress
ruflo task list

# View agent logs
ruflo agent logs agent-ID
```

### 7. Collect Results
```bash
# When swarm finishes, results are in the project directory
git status  # See all files created/modified

# If issues, create new tasks and assign
ruflo task create -t fix -d "Fix issue X"
ruflo task assign task-ID --agent agent-name
```

---

## Agent Types & When to Use

| Agent Type | Best For | Model | Example |
|-----------|----------|-------|---------|
| **architect** | System design, high-level decisions | Sonnet | Design DB schema, plan microservices |
| **coder** | Writing code, refactoring, implementation | Sonnet/Haiku | Implement service, write dockerfile |
| **tester** | Unit/integration/E2E tests, validation | Sonnet | Write test suite, run E2E |
| **reviewer** | Code review, security audit, QA | Sonnet | Review PR, find bugs |
| **researcher** | Documentation, analysis, research | Haiku | Document API, research patterns |
| **security-auditor** | CVE scanning, threat modeling, hardening | Sonnet | Audit code, find vulnerabilities |
| **performance-engineer** | Optimization, profiling, benchmarking | Sonnet | Optimize queries, reduce latency |
| **memory-specialist** | Memory patterns, caching, optimization | Sonnet | Design memory layer, cache policies |

---

## Best Practices

### ✅ DO

1. **Use swarm for complex multi-part tasks**
   ```bash
   ruflo swarm start --objective "Build entire trading system with tests and docs"
   ```

2. **Break work into discrete subtasks**
   ```bash
   # Good: Each task is independent
   ruflo task create -t implementation -d "Build service X"
   ruflo task create -t testing -d "Test service X"
   ruflo task create -t documentation -d "Document service X"
   ```

3. **Assign tasks to appropriate agents**
   ```bash
   # Architect first, then coders in parallel, then testers
   ruflo task assign task-design --agent architect
   ruflo task assign task-code-1 --agent coder-1 &
   ruflo task assign task-code-2 --agent coder-2 &
   ruflo task assign task-test --agent tester-1
   wait
   ```

4. **Use hive-mind for hands-off execution**
   ```bash
   # Let swarm auto-route tasks and execute in parallel
   ruflo hive-mind spawn --claude --swarm swarm-ID --workers 8
   ```

5. **Store patterns in memory after successful tasks**
   ```bash
   ruflo memory store --key "docker-pattern" --value "..." --namespace patterns
   ```

### ❌ DON'T

1. **Don't create one big task**
   ```bash
   # Bad: Everything in one task
   ruflo task create -t implementation -d "Build entire system"
   
   # Good: Break into subtasks
   ruflo task create -t implementation -d "Build service A"
   ruflo task create -t implementation -d "Build service B"
   ruflo task create -t testing -d "Test services A+B"
   ```

2. **Don't manually run agents in series**
   ```bash
   # Bad: Sequential execution
   ruflo task assign task-1 --agent coder-1
   ruflo task assign task-2 --agent coder-2  # Waits for task-1
   
   # Good: Parallel execution
   ruflo task assign task-1 --agent coder-1 &
   ruflo task assign task-2 --agent coder-2 &
   wait
   ```

3. **Don't skip architect phase for complex work**
   ```bash
   # Bad: Jump straight to coding
   ruflo task create -t implementation -d "Code it"
   
   # Good: Design first
   ruflo task create -t design -d "Plan architecture"
   ruflo task assign task-design --agent architect
   # WAIT FOR COMPLETION
   ruflo task create -t implementation -d "Code based on design"
   ```

4. **Don't use swarm for simple one-liner tasks**
   ```bash
   # Bad: Overkill
   ruflo swarm start --objective "Add a logging line"
   
   # Good: Just edit directly
   # OR use single agent
   ruflo agent spawn -t coder --name quick-fix
   ```

---

## Common Workflows

### Workflow 1: Build a New Microservice
```bash
# 1. Start swarm
cd /tmp/tank-docker-setup
ruflo swarm start --objective "Build new analytics microservice with dockerfile, tests, docs"

# 2. Create subtasks
ruflo task create -t design -d "Design analytics service schema and API"
ruflo task create -t implementation -d "Build app.py for analytics service"
ruflo task create -t implementation -d "Write Dockerfile for analytics service"
ruflo task create -t testing -d "Write unit and integration tests"
ruflo task create -t documentation -d "Document API and setup"

# 3. Spawn agents
ruflo agent spawn -t architect --name arch-analytics --model sonnet
ruflo agent spawn -t coder --name coder-app --model sonnet
ruflo agent spawn -t coder --name coder-docker --model sonnet
ruflo agent spawn -t tester --name tester-analytics --model sonnet

# 4. Assign tasks sequentially for dependencies
ruflo task assign task-design --agent arch-analytics
# WAIT FOR COMPLETION
ruflo task assign task-app --agent coder-app &
ruflo task assign task-docker --agent coder-docker &
wait
ruflo task assign task-test --agent tester-analytics
```

### Workflow 2: Refactor with Tests
```bash
# 1. Start swarm
ruflo swarm start --objective "Refactor auth service: split into microservices, add RBAC, write tests"

# 2. Create subtasks
ruflo task create -t design -d "Design new auth architecture with RBAC"
ruflo task create -t implementation -d "Implement RBAC module"
ruflo task create -t implementation -d "Implement token validation module"
ruflo task create -t implementation -d "Implement permission checking module"
ruflo task create -t testing -d "Write unit tests for RBAC"
ruflo task create -t testing -d "Write E2E tests for auth flow"
ruflo task create -t security -d "Security audit of auth implementation"

# 3. Use hive-mind for autonomous execution
ruflo hive-mind init
ruflo hive-mind spawn --claude --swarm swarm-ID --workers 8
# Watch it go!
```

### Workflow 3: Bug Fix Sprint
```bash
# 1. Start swarm
ruflo swarm start --objective "Fix critical bugs in trading system"

# 2. Create tasks for each bug
ruflo task create -t fix -d "Fix race condition in order executor"
ruflo task create -t fix -d "Fix memory leak in portfolio tracker"
ruflo task create -t fix -d "Fix null pointer in signal generator"

# 3. Spawn fixers
ruflo agent spawn -t coder --name bugfixer-1 --model sonnet
ruflo agent spawn -t coder --name bugfixer-2 --model sonnet
ruflo agent spawn -t coder --name bugfixer-3 --model sonnet

# 4. Assign all in parallel
ruflo task assign task-bug-1 --agent bugfixer-1 &
ruflo task assign task-bug-2 --agent bugfixer-2 &
ruflo task assign task-bug-3 --agent bugfixer-3 &
wait

# 5. Verify and commit
git status
git add -A
git commit -m "fix: critical bug fixes in trading system"
git push
```

---

## Token Cost Optimization

### How Swarm Reduces Costs

1. **Parallel Execution**
   - Sequential: 3 tasks × Sonnet tokens = 3× Sonnet cost
   - Parallel: 3 tasks × Sonnet ÷ 3 workers = Same tokens, 3× faster

2. **Smart Model Routing**
   - Simple tasks → Haiku (50% cheaper)
   - Medium tasks → Sonnet (balanced)
   - Complex tasks → Opus (best quality)

3. **Memory Reuse**
   - SONA stores patterns from successful tasks
   - Second build reuses patterns → 30% fewer tokens

4. **Task Granularity**
   - Small focused tasks → Lower tokens per task
   - Architect decides complexity, routes to right model

### Example Cost Comparison

**Without Swarm (Sequential):**
- Task 1 (design): 50K tokens (Sonnet)
- Task 2 (code): 100K tokens (Sonnet)
- Task 3 (test): 75K tokens (Sonnet)
- **Total: 225K tokens, 10 hours**

**With Swarm (Parallel):**
- Task 1 (design): 50K tokens (Sonnet) — Architect
- Task 2 (code): 100K tokens (Sonnet) — Coder-1
- Task 3 (test): 75K tokens (Sonnet) — Tester-1
- **Total: 225K tokens, 3 hours (3x faster)**
- **With SONA pattern reuse: ~160K tokens on next run (30% savings)**

---

## Troubleshooting

### Swarm Not Starting
```bash
# Check if swarm exists
ruflo swarm status swarm-ID

# If not, initialize
ruflo swarm start --objective "..."
```

### Tasks Not Executing
```bash
# Check task status
ruflo task list

# Check agent status
ruflo agent list

# If agents are idle, start hive-mind
ruflo hive-mind spawn --claude --swarm swarm-ID
```

### Agent Stuck/Hung
```bash
# Force stop agent
ruflo agent stop agent-ID

# Kill entire swarm
ruflo swarm cancel swarm-ID

# Restart
ruflo swarm start --objective "..."
```

### Memory Not Learning
```bash
# Manually store successful pattern
ruflo memory store --key "pattern-name" --value "..." --namespace patterns

# Verify storage
ruflo memory search "pattern-name"
```

---

## Integration with Tank Trading System

### Using Swarm for Trading System Development

```bash
# Strategy Development Swarm
ruflo swarm start --objective "Implement new trading strategy: research patterns, backtest, optimize, deploy"

# Tasks
ruflo task create -t research -d "Research XYZ strategy patterns in academic literature"
ruflo task create -t implementation -d "Implement strategy in Python"
ruflo task create -t implementation -d "Integrate with backtester"
ruflo task create -t testing -d "Backtest on historical data"
ruflo task create -t optimization -d "Genetic algorithm optimization"
ruflo task create -t deployment -d "Deploy to tournament runner"

# Assign
ruflo agent spawn -t researcher --name strategy-researcher --model sonnet
ruflo agent spawn -t coder --name strategy-coder --model sonnet
ruflo agent spawn -t coder --name backtest-integrator --model sonnet
ruflo agent spawn -t tester --name backtest-validator --model sonnet
ruflo agent spawn -t performance-engineer --name optimizer --model sonnet

# Execute
ruflo task assign task-research --agent strategy-researcher
# WAIT
ruflo task assign task-impl --agent strategy-coder &
ruflo task assign task-integrate --agent backtest-integrator &
wait
ruflo task assign task-test --agent backtest-validator
# WAIT
ruflo task assign task-opt --agent optimizer
# WAIT
ruflo task assign task-deploy --agent deployer
```

---

## Key Takeaways

1. **Swarm = Parallel Claude Code execution** — Multiple agents work simultaneously
2. **Hive-Mind = Autonomous routing** — Queen coordinator auto-assigns tasks to best agents
3. **Claude Code integration** — Workers execute actual code (write files, run tests, commit to git)
4. **Token efficient** — Parallel execution + smart model routing = lower costs
5. **Self-learning** — SONA learns which agents work best for each task type
6. **Use for complex multi-part projects** — Architecture design → parallel implementation → testing → deployment

**Golden Rule:** Break work into discrete subtasks, assign to appropriate agents, let swarm execute in parallel with hive-mind automation.

---

## Links & Resources

- **Ruflo Official:** https://github.com/ruvnet/ruflo
- **MCP Integration:** Works with Claude Code, Cursor, VS Code, ChatGPT via MCP server
- **Discord Community:** https://discord.com/invite/clawd
