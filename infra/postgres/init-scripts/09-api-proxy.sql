-- api-proxy service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS rate_limits (
    id BIGSERIAL PRIMARY KEY,
    client_ip TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_count INTEGER DEFAULT 1,
    window_start TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_ip, endpoint, window_start)
);

CREATE TABLE IF NOT EXISTS proxy_routes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    path_pattern TEXT NOT NULL UNIQUE,
    target_service TEXT NOT NULL,
    target_port INTEGER NOT NULL,
    methods TEXT[] DEFAULT ARRAY['GET','POST'],
    auth_required BOOLEAN DEFAULT true,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default routes
INSERT INTO proxy_routes (path_pattern, target_service, target_port, methods) VALUES
    ('/api/research/*', 'tank-research', 8002, ARRAY['GET','POST']),
    ('/api/decision/*', 'tank-decision', 8003, ARRAY['GET','POST']),
    ('/api/executor/*', 'tank-executor', 8004, ARRAY['GET','POST']),
    ('/api/ledger/*', 'tank-ledger', 8005, ARRAY['GET']),
    ('/api/tournament/*', 'tank-tournament', 8006, ARRAY['GET','POST'])
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_rate_limits_client ON rate_limits(client_ip);
CREATE INDEX IF NOT EXISTS idx_proxy_routes_path ON proxy_routes(path_pattern);
