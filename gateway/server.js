'use strict';

const express = require('express');
const morgan  = require('morgan');
const http    = require('http');
const https   = require('https');
const WebSocket = require('ws');
const Redis   = require('ioredis');
const { v4: uuidv4 } = require('uuid');
const promClient = require('prom-client');

// ── Config ───────────────────────────────────────────────────
const PORT         = parseInt(process.env.OPENCLAW_PORT || '18789', 10);
const SECRET       = process.env.OPENCLAW_SECRET       || 'changeme_openclaw_secret';
const ADMIN_TOKEN  = process.env.OPENCLAW_ADMIN_TOKEN  || 'changeme_admin_token';
const TANK_URL     = process.env.TANK_AGENT_URL        || 'http://tank-agent:9000';

const SERVICE_PORTS = {
  'api-proxy': 8001, 'research': 8002, 'decision': 8003, 'executor': 8004,
  'ledger': 8005, 'tournament': 8006, 'monitor': 8007, 'memory-sync': 8008,
  'banks-service': 8009, 'meta-builder': 8010, 'risk-manager': 8011,
  'portfolio-tracker': 8012, 'market-data': 8013, 'signal-generator': 8014,
  'order-router': 8015, 'position-manager': 8016, 'alert-service': 8017,
  'report-generator': 8018, 'backtest-runner': 8019, 'strategy-optimizer': 8020,
  'feed-aggregator': 8021, 'auth-service': 8022, 'notification-service': 8023,
  'analytics-service': 8024,
};

// ── In-memory stores ─────────────────────────────────────────
const agents   = new Map(); // id → { id, name, url, capabilities, connected, last_seen, ws? }
const sessions = new Map(); // session_id → { session_id, created_at }
const pending  = new Map(); // session_id → { resolve, reject, timer }

// ── Redis ────────────────────────────────────────────────────
const redis = new Redis({
  host: process.env.REDIS_HOST     || 'redis',
  port: parseInt(process.env.REDIS_PORT || '6379', 10),
  password: process.env.REDIS_PASSWORD || undefined,
  lazyConnect: true,
  enableOfflineQueue: false,
});
redis.on('error', (err) => console.warn('[redis] error:', err.message));
redis.connect().catch((err) => console.warn('[redis] connect failed:', err.message));

// ── Prometheus ───────────────────────────────────────────────
promClient.collectDefaultMetrics();

const httpRequestsTotal = new promClient.Counter({
  name: 'http_requests_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'path', 'status'],
});
const wsConnectionsActive = new promClient.Gauge({
  name: 'ws_connections_active',
  help: 'Active WebSocket connections',
});
const messagesTotal = new promClient.Counter({
  name: 'messages_total',
  help: 'Total messages routed',
  labelNames: ['from', 'to'],
});
const messageDuration = new promClient.Histogram({
  name: 'message_duration_seconds',
  help: 'Message routing duration',
  buckets: [0.01, 0.05, 0.1, 0.5, 1, 2, 5],
});

// ── Helpers ──────────────────────────────────────────────────
function httpPost(url, body) {
  return new Promise((resolve, reject) => {
    const data   = JSON.stringify(body);
    const parsed = new URL(url);
    const lib    = parsed.protocol === 'https:' ? https : http;
    const req = lib.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    }, (res) => {
      let buf = '';
      res.on('data', (c) => { buf += c; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(buf) }); }
        catch { resolve({ status: res.statusCode, body: buf }); }
      });
    });
    req.setTimeout(10000, () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

async function redisPublish(from, to, content) {
  try {
    await redis.xadd('tank:events', '*', 'from', from || '', 'to', to || '', 'content', content || '', 'ts', Date.now().toString());
  } catch (err) {
    console.warn('[redis] xadd failed:', err.message);
  }
}

async function redisSetAgent(agent) {
  try {
    await redis.set(`agents:${agent.id}`, JSON.stringify(agent), 'EX', 300);
  } catch (err) {
    console.warn('[redis] set agent failed:', err.message);
  }
}

// Route a message to an agent (WS or HTTP fallback)
async function routeMessage(to, content, from, session_id) {
  const end = messageDuration.startTimer();
  messagesTotal.inc({ from: from || 'unknown', to: to || 'unknown' });
  try {
    // Try registered WS agent first
    const agent = agents.get(to);
    if (agent && agent.connected && agent.ws && agent.ws.readyState === WebSocket.OPEN) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(session_id);
          reject(new Error('WS response timeout'));
        }, 15000);
        pending.set(session_id, { resolve, reject, timer });
        agent.ws.send(JSON.stringify({ type: 'message', from, content, session_id }));
      });
    }
    // HTTP fallback
    const targetUrl = agent && agent.url ? agent.url : `${TANK_URL}/message`;
    const result = await httpPost(targetUrl, { to, content, from, session_id });
    return result.body;
  } finally {
    end();
  }
}

// Route slash command
async function routeSlash(content, from, session_id) {
  const parts   = content.slice(1).split(/\s+/);
  const [target, ...rest] = parts[0].split('/');
  const method  = rest.join('/') || 'command';
  const args    = parts.slice(1).join(' ');

  // Try WS agent by name
  for (const [, agent] of agents) {
    if (agent.name === target && agent.connected && agent.ws && agent.ws.readyState === WebSocket.OPEN) {
      return routeMessage(agent.id, content, from, session_id);
    }
  }

  // HTTP fallback using service port map
  const port = SERVICE_PORTS[target];
  if (!port) throw new Error(`Unknown service: ${target}`);
  const url = `http://${target}:${port}/${method}`;
  const result = await httpPost(url, { args, from, session_id });
  return result.body;
}

// ── Express ──────────────────────────────────────────────────
const app = express();
app.use(morgan('combined'));
app.use(express.json());
app.use((req, res, next) => {
  res.on('finish', () => httpRequestsTotal.inc({ method: req.method, path: req.path, status: String(res.statusCode) }));
  next();
});

// Health
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', agents: agents.size, uptime: Math.floor(process.uptime()), version: '1.0.0' });
});

// Metrics
app.get('/metrics', async (_req, res) => {
  try {
    res.set('Content-Type', promClient.register.contentType);
    res.end(await promClient.register.metrics());
  } catch (err) {
    res.status(500).end(err.message);
  }
});

// Agent registration
app.post('/agents/register', async (req, res) => {
  const { id = uuidv4(), name, url = '', capabilities = [] } = req.body || {};
  if (!name) return res.status(400).json({ error: 'name required' });
  const agent = { id, name, url, capabilities, connected: false, last_seen: new Date().toISOString() };
  agents.set(id, agent);
  await redisSetAgent(agent);
  res.json({ ok: true, id });
});

// List agents
app.get('/agents', (_req, res) => {
  const list = Array.from(agents.values()).map(({ ws: _ws, ...rest }) => rest);
  res.json(list);
});

// Remove agent
app.delete('/agents/:id', (req, res) => {
  const agent = agents.get(req.params.id);
  if (!agent) return res.status(404).json({ error: 'not found' });
  if (agent.ws) try { agent.ws.close(); } catch {}
  agents.delete(req.params.id);
  res.json({ ok: true });
});

// Route message
app.post('/message', async (req, res) => {
  const { to, content, from, session_id = uuidv4() } = req.body || {};
  if (!to || !content) return res.status(400).json({ error: 'to and content required' });
  try {
    await redisPublish(from, to, content);
    const response = await routeMessage(to, content, from, session_id);
    res.json({ ok: true, session_id, response });
  } catch (err) {
    console.error('[message] routing error:', err.message);
    res.status(502).json({ error: err.message });
  }
});

// Sessions
app.get('/sessions', (_req, res) => {
  res.json(Array.from(sessions.values()));
});

app.post('/sessions', (req, res) => {
  const session_id = uuidv4();
  const session = { session_id, created_at: new Date().toISOString(), ...req.body };
  sessions.set(session_id, session);
  res.status(201).json({ session_id, created_at: session.created_at });
});

app.get('/sessions/:id', (req, res) => {
  const session = sessions.get(req.params.id);
  if (!session) return res.status(404).json({ error: 'not found' });
  res.json(session);
});

// ── HTTP + WebSocket server ──────────────────────────────────
const server = http.createServer(app);
const wss = new WebSocket.Server({ server, path: '/ws' });

wss.on('connection', (ws) => {
  wsConnectionsActive.inc();
  let agentId = null;
  let alive   = true;

  ws.on('pong', () => { alive = true; });

  ws.on('message', async (raw) => {
    let msg;
    try { msg = JSON.parse(raw.toString()); } catch { return; }

    if (msg.type === 'register') {
      const { id = uuidv4(), name, capabilities = [] } = msg;
      if (!name) return ws.send(JSON.stringify({ type: 'error', error: 'name required' }));
      agentId = id;
      const agent = agents.get(id) || { id, name, url: '', capabilities, connected: true, last_seen: new Date().toISOString() };
      agent.ws = ws;
      agent.connected = true;
      agent.last_seen  = new Date().toISOString();
      agents.set(id, agent);
      await redisSetAgent(agent);
      ws.send(JSON.stringify({ type: 'registered', id }));

    } else if (msg.type === 'message') {
      const { to, content, session_id = uuidv4() } = msg;
      if (!to || !content) return ws.send(JSON.stringify({ type: 'error', error: 'to and content required' }));
      const from = agentId;
      await redisPublish(from, to, content);
      try {
        const response = await routeMessage(to, content, from, session_id);
        ws.send(JSON.stringify({ type: 'response', session_id, response }));
      } catch (err) {
        ws.send(JSON.stringify({ type: 'error', session_id, error: err.message }));
      }

    } else if (msg.type === 'heartbeat') {
      ws.send(JSON.stringify({ type: 'heartbeat_ack' }));

    } else if (msg.type === 'response') {
      const { session_id, content } = msg;
      const cb = pending.get(session_id);
      if (cb) {
        clearTimeout(cb.timer);
        pending.delete(session_id);
        cb.resolve(content);
      }
    }
  });

  ws.on('close', () => {
    wsConnectionsActive.dec();
    if (agentId) {
      const agent = agents.get(agentId);
      if (agent) { agent.connected = false; agent.ws = null; agent.last_seen = new Date().toISOString(); }
    }
  });

  ws.on('error', (err) => console.warn('[ws] client error:', err.message));
});

// Ping loop — remove stale connections after 10s with no pong
const pingInterval = setInterval(() => {
  wss.clients.forEach((ws) => {
    if (ws._alive === false) { ws.terminate(); return; }
    ws._alive = false;
    ws.ping();
  });
  // track alive state per-socket via _alive flag
}, 30000);

wss.clients.forEach = function(cb) {
  WebSocket.Server.prototype.clients.forEach.call(this.clients, cb);
};

// Properly wire _alive on each new connection
wss.on('connection', (ws) => {
  ws._alive = true;
  ws.on('pong', () => { ws._alive = true; });
});

// ── Graceful shutdown ────────────────────────────────────────
process.on('SIGTERM', () => {
  console.log('[openclaw-gateway] SIGTERM received, shutting down');
  clearInterval(pingInterval);
  wss.close(() => {
    redis.disconnect();
    server.close(() => {
      console.log('[openclaw-gateway] shutdown complete');
      process.exit(0);
    });
  });
});

// ── Start ────────────────────────────────────────────────────
server.listen(PORT, () => {
  console.log(`[openclaw-gateway] listening on :${PORT}`);
});
