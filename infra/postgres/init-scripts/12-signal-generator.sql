-- signal-generator schema (uses research DB)
\c research

CREATE TABLE IF NOT EXISTS generated_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal TEXT NOT NULL CHECK (signal IN ('buy','sell','hold')),
    score FLOAT NOT NULL CHECK (score BETWEEN -1 AND 1),
    indicators JSONB DEFAULT '{}',
    timeframe TEXT DEFAULT '1h',
    valid_until TIMESTAMPTZ,
    published BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS indicator_values (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    indicator TEXT NOT NULL,
    value FLOAT NOT NULL,
    timeframe TEXT DEFAULT '1h',
    calc_time TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gen_signals_symbol ON generated_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_gen_signals_strategy ON generated_signals(strategy);
CREATE INDEX IF NOT EXISTS idx_indicator_values_symbol ON indicator_values(symbol, indicator);
