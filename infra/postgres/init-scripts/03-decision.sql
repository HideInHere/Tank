-- decision service schema
\c decision
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy','sell','hold')),
    confidence FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    rationale TEXT,
    strategy_name TEXT,
    consensus_votes JSONB DEFAULT '[]',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','executed','cancelled','expired')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS strategy_evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_name TEXT NOT NULL,
    params JSONB DEFAULT '{}',
    score FLOAT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS votes (
    id BIGSERIAL PRIMARY KEY,
    decision_id UUID REFERENCES decisions(id) ON DELETE CASCADE,
    voter TEXT NOT NULL,
    vote TEXT NOT NULL,
    confidence FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at DESC);
