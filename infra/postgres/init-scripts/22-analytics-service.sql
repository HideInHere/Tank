-- analytics-service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGSERIAL PRIMARY KEY,
    event_name TEXT NOT NULL,
    properties JSONB DEFAULT '{}',
    user_id TEXT,
    session_id TEXT,
    ip_address INET,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics_aggregated (
    id BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    dimension TEXT,
    dimension_value TEXT,
    period TEXT NOT NULL CHECK (period IN ('minute','hour','day','week','month')),
    period_start TIMESTAMPTZ NOT NULL,
    value NUMERIC(18,8),
    count INTEGER DEFAULT 1,
    UNIQUE(metric_name, dimension, dimension_value, period, period_start)
);

CREATE TABLE IF NOT EXISTS dashboards (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    owner TEXT,
    widgets JSONB DEFAULT '[]',
    public BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_events_name ON analytics_events(event_name);
CREATE INDEX IF NOT EXISTS idx_analytics_events_time ON analytics_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_agg_name ON metrics_aggregated(metric_name, period, period_start DESC);
