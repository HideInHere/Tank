-- memory-sync service schema
\c memory
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS memory_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key TEXT NOT NULL UNIQUE,
    value JSONB NOT NULL,
    category TEXT DEFAULT 'general',
    tags TEXT[],
    ttl_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_log (
    id BIGSERIAL PRIMARY KEY,
    operation TEXT NOT NULL CHECK (operation IN ('backup','restore','sync','purge')),
    entries_affected INTEGER DEFAULT 0,
    github_ref TEXT,
    status TEXT DEFAULT 'success' CHECK (status IN ('success','failed','partial')),
    error_msg TEXT,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_context (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id TEXT NOT NULL,
    context_type TEXT NOT NULL,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, context_type)
);

CREATE INDEX IF NOT EXISTS idx_memory_key ON memory_entries(key);
CREATE INDEX IF NOT EXISTS idx_memory_category ON memory_entries(category);
CREATE INDEX IF NOT EXISTS idx_memory_expires ON memory_entries(expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_context ON agent_context(agent_id);
