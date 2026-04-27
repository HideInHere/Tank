-- Unleash feature flags DB setup
-- Unleash manages its own schema; this creates the DB
\c postgres

SELECT 'CREATE DATABASE unleash'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'unleash')\gexec

\c unleash
-- Unleash creates its own schema on startup
-- This file seeds tank-specific feature flags table for custom tracking
CREATE TABLE IF NOT EXISTS tank_feature_flags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    flag_name TEXT NOT NULL UNIQUE,
    description TEXT,
    enabled BOOLEAN DEFAULT false,
    rollout_percent INTEGER DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default feature flags
INSERT INTO tank_feature_flags (flag_name, description, enabled, rollout_percent) VALUES
    ('live-trading', 'Enable live order execution', false, 0),
    ('ml-signals', 'Enable ML-based signal generation', false, 0),
    ('auto-backtest', 'Enable automatic strategy backtesting', true, 100),
    ('grpc-comms', 'Use gRPC for inter-service communication', true, 100),
    ('telegram-alerts', 'Enable Telegram notifications', true, 100)
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_tank_flags_enabled ON tank_feature_flags(enabled) WHERE enabled = true;
