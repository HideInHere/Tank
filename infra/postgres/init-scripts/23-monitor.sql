-- monitor service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS health_checks (
    id BIGSERIAL PRIMARY KEY,
    service_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('healthy','unhealthy','degraded','unknown')),
    response_time_ms INTEGER,
    error_msg TEXT,
    details JSONB DEFAULT '{}',
    checked_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name TEXT,
    alert_name TEXT NOT NULL,
    severity TEXT DEFAULT 'warning' CHECK (severity IN ('info','warning','critical','resolved')),
    message TEXT,
    labels JSONB DEFAULT '{}',
    firing BOOLEAN DEFAULT true,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS service_logs (
    id BIGSERIAL PRIMARY KEY,
    service_name TEXT NOT NULL,
    level TEXT DEFAULT 'info' CHECK (level IN ('debug','info','warning','error','critical')),
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    logged_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_health_checks_service ON health_checks(service_name);
CREATE INDEX IF NOT EXISTS idx_health_checks_time ON health_checks(checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_service ON alerts(service_name);
CREATE INDEX IF NOT EXISTS idx_alerts_firing ON alerts(firing) WHERE firing = true;
CREATE INDEX IF NOT EXISTS idx_service_logs_service ON service_logs(service_name);
CREATE INDEX IF NOT EXISTS idx_service_logs_level ON service_logs(level);
