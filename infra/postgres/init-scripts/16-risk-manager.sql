-- risk-manager schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS risk_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('position_limit','drawdown','concentration','volatility','daily_loss')),
    threshold NUMERIC(18,8) NOT NULL,
    action TEXT DEFAULT 'alert' CHECK (action IN ('alert','block','reduce','liquidate')),
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID REFERENCES risk_rules(id),
    symbol TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT DEFAULT 'warning' CHECK (severity IN ('info','warning','critical')),
    message TEXT,
    value NUMERIC(18,8),
    threshold NUMERIC(18,8),
    acknowledged BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_metrics (
    id BIGSERIAL PRIMARY KEY,
    var_1d FLOAT,
    var_5d FLOAT,
    max_drawdown FLOAT,
    sharpe_ratio FLOAT,
    beta FLOAT,
    correlation_matrix JSONB DEFAULT '{}',
    calc_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default risk rules
INSERT INTO risk_rules (name, rule_type, threshold, action) VALUES
    ('max-position-size', 'position_limit', 0.10, 'block'),
    ('daily-loss-limit', 'daily_loss', 0.05, 'block'),
    ('max-drawdown', 'drawdown', 0.20, 'liquidate')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_risk_alerts_rule ON risk_alerts(rule_id);
CREATE INDEX IF NOT EXISTS idx_risk_alerts_severity ON risk_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_risk_alerts_ack ON risk_alerts(acknowledged) WHERE acknowledged = false;
