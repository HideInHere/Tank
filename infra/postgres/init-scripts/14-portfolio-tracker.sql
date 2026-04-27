-- portfolio-tracker schema (uses ledger DB)
\c ledger

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID,
    total_value NUMERIC(18,8) NOT NULL,
    cash NUMERIC(18,8) NOT NULL,
    invested NUMERIC(18,8) NOT NULL,
    unrealized_pnl NUMERIC(18,8) DEFAULT 0,
    realized_pnl NUMERIC(18,8) DEFAULT 0,
    positions_count INTEGER DEFAULT 0,
    snapshot_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_analytics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC(18,8),
    period TEXT,
    calc_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_account ON portfolio_snapshots(account_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_time ON portfolio_snapshots(snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_portfolio_analytics_account ON portfolio_analytics(account_id);
