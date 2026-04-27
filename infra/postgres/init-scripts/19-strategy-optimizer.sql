-- strategy-optimizer schema (uses decision DB)
\c decision

CREATE TABLE IF NOT EXISTS strategies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    params JSONB DEFAULT '{}',
    version INTEGER DEFAULT 1,
    active BOOLEAN DEFAULT false,
    performance_score FLOAT,
    last_optimized TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS optimization_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id),
    method TEXT NOT NULL CHECK (method IN ('grid_search','bayesian','genetic','random')),
    param_space JSONB DEFAULT '{}',
    best_params JSONB DEFAULT '{}',
    best_score FLOAT,
    iterations INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default strategies
INSERT INTO strategies (name, description, params, active) VALUES
    ('momentum', 'Trend following momentum strategy', '{"lookback": 20, "threshold": 0.02}', true),
    ('mean_reversion', 'Statistical mean reversion', '{"window": 30, "z_score": 2.0}', true),
    ('ml_ensemble', 'ML ensemble predictions', '{"models": ["rf","xgb","lstm"]}', false)
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_strategies_active ON strategies(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_opt_runs_strategy ON optimization_runs(strategy_id);
