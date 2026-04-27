-- alert-service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS alert_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    condition_expr TEXT NOT NULL,
    threshold NUMERIC(18,8),
    comparison TEXT CHECK (comparison IN ('gt','lt','gte','lte','eq','ne')),
    channel TEXT DEFAULT 'telegram',
    cooldown_minutes INTEGER DEFAULT 5,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fired_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id UUID REFERENCES alert_rules(id),
    triggered_value NUMERIC(18,8),
    message TEXT,
    channel TEXT,
    delivered BOOLEAN DEFAULT false,
    fired_at TIMESTAMPTZ DEFAULT NOW(),
    delivered_at TIMESTAMPTZ
);

-- Default alert rules
INSERT INTO alert_rules (name, condition_expr, threshold, comparison, channel) VALUES
    ('high-drawdown', 'portfolio.drawdown', 0.10, 'gt', 'telegram'),
    ('service-down', 'health.consecutive_failures', 3, 'gte', 'telegram'),
    ('large-order', 'order.quantity_usd', 10000, 'gt', 'telegram')
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON alert_rules(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_fired_alerts_rule ON fired_alerts(rule_id);
CREATE INDEX IF NOT EXISTS idx_fired_alerts_delivered ON fired_alerts(delivered) WHERE delivered = false;
