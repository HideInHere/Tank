-- executor service schema
\c executor
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy','sell')),
    order_type TEXT DEFAULT 'market' CHECK (order_type IN ('market','limit','stop','stop_limit')),
    quantity NUMERIC(18,8) NOT NULL,
    price NUMERIC(18,8),
    stop_price NUMERIC(18,8),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','submitted','filled','partial','cancelled','rejected','expired')),
    exchange TEXT,
    exchange_order_id TEXT,
    fill_price NUMERIC(18,8),
    fill_qty NUMERIC(18,8),
    fees NUMERIC(18,8) DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id BIGSERIAL PRIMARY KEY,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    event TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    logged_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exec_logs_order ON execution_logs(order_id);
