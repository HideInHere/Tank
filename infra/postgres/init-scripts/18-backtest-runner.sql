-- backtest-runner schema (uses research DB)
\c research

CREATE TABLE IF NOT EXISTS backtests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_capital NUMERIC(18,8) DEFAULT 100000,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    results JSONB DEFAULT '{}',
    total_return FLOAT,
    sharpe_ratio FLOAT,
    max_drawdown FLOAT,
    win_rate FLOAT,
    total_trades INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id BIGSERIAL PRIMARY KEY,
    backtest_id UUID REFERENCES backtests(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity NUMERIC(18,8),
    entry_price NUMERIC(18,8),
    exit_price NUMERIC(18,8),
    pnl NUMERIC(18,8),
    entry_time TIMESTAMPTZ,
    exit_time TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_backtests_strategy ON backtests(strategy);
CREATE INDEX IF NOT EXISTS idx_backtests_status ON backtests(status);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_bt ON backtest_trades(backtest_id);
