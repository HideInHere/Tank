-- order-router schema (uses executor DB)
\c executor

CREATE TABLE IF NOT EXISTS routing_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    conditions JSONB DEFAULT '{}',
    target_exchange TEXT NOT NULL,
    priority INTEGER DEFAULT 100,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS routed_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_order_id UUID,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    routing_rule TEXT,
    latency_ms INTEGER,
    routed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default routing rules
INSERT INTO routing_rules (name, conditions, target_exchange, priority) VALUES
    ('default-equity', '{"asset_class": "equity"}', 'paper_broker', 100),
    ('default-crypto', '{"asset_class": "crypto"}', 'paper_crypto', 100)
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_routed_orders_symbol ON routed_orders(symbol);
CREATE INDEX IF NOT EXISTS idx_routing_rules_priority ON routing_rules(priority DESC);
