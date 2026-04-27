-- ledger service schema
\c ledger
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    currency TEXT DEFAULT 'USD',
    balance NUMERIC(18,8) DEFAULT 0,
    equity NUMERIC(18,8) DEFAULT 0,
    margin_used NUMERIC(18,8) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID REFERENCES accounts(id),
    tx_type TEXT NOT NULL CHECK (tx_type IN ('deposit','withdrawal','trade','fee','dividend','adjustment')),
    amount NUMERIC(18,8) NOT NULL,
    currency TEXT DEFAULT 'USD',
    reference_id TEXT,
    description TEXT,
    balance_after NUMERIC(18,8),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID REFERENCES accounts(id),
    symbol TEXT NOT NULL,
    quantity NUMERIC(18,8) NOT NULL,
    avg_cost NUMERIC(18,8) NOT NULL,
    current_price NUMERIC(18,8),
    unrealized_pnl NUMERIC(18,8),
    realized_pnl NUMERIC(18,8) DEFAULT 0,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    UNIQUE(account_id, symbol)
);

-- Insert default account
INSERT INTO accounts (name, currency, balance, equity) VALUES ('main', 'USD', 100000, 100000) ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_txns_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_txns_created ON transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
