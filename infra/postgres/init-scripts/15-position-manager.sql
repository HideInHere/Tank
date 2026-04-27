-- position-manager schema (uses ledger DB)
\c ledger

CREATE TABLE IF NOT EXISTS position_history (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    account_id UUID,
    action TEXT NOT NULL CHECK (action IN ('open','increase','decrease','close')),
    quantity_delta NUMERIC(18,8) NOT NULL,
    price NUMERIC(18,8) NOT NULL,
    reason TEXT,
    pnl_realized NUMERIC(18,8),
    acted_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stop_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    account_id UUID,
    stop_type TEXT NOT NULL CHECK (stop_type IN ('stop_loss','take_profit','trailing_stop')),
    trigger_price NUMERIC(18,8) NOT NULL,
    trail_percent FLOAT,
    quantity NUMERIC(18,8),
    active BOOLEAN DEFAULT true,
    triggered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_position_history_symbol ON position_history(symbol);
CREATE INDEX IF NOT EXISTS idx_stop_orders_symbol ON stop_orders(symbol);
CREATE INDEX IF NOT EXISTS idx_stop_orders_active ON stop_orders(active) WHERE active = true;
