-- tournament service schema
\c tournament
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS tournaments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    start_date TIMESTAMPTZ,
    end_date TIMESTAMPTZ,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','active','completed','cancelled')),
    rules JSONB DEFAULT '{}',
    prize_pool NUMERIC(18,8) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS participants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tournament_id UUID REFERENCES tournaments(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    strategy TEXT,
    score NUMERIC(18,8) DEFAULT 0,
    rank INTEGER,
    pnl NUMERIC(18,8) DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    win_rate FLOAT DEFAULT 0,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tournament_id, agent_name)
);

CREATE TABLE IF NOT EXISTS tournament_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    participant_id UUID REFERENCES participants(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity NUMERIC(18,8),
    price NUMERIC(18,8),
    pnl NUMERIC(18,8),
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tournaments_status ON tournaments(status);
CREATE INDEX IF NOT EXISTS idx_participants_tournament ON participants(tournament_id);
CREATE INDEX IF NOT EXISTS idx_participants_rank ON participants(rank);
