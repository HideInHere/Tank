-- banks service schema
\c banks
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS build_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','failed','cancelled')),
    priority TEXT DEFAULT 'normal' CHECK (priority IN ('low','normal','high','critical')),
    assignee TEXT,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name TEXT NOT NULL,
    version TEXT NOT NULL,
    environment TEXT DEFAULT 'production' CHECK (environment IN ('dev','staging','production')),
    status TEXT DEFAULT 'pending',
    deployed_by TEXT,
    config JSONB DEFAULT '{}',
    deployed_at TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS code_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pr_url TEXT,
    title TEXT,
    status TEXT DEFAULT 'open' CHECK (status IN ('open','approved','rejected','merged')),
    reviewer_notes TEXT,
    reviewed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_build_tasks_status ON build_tasks(status);
CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_name);
CREATE INDEX IF NOT EXISTS idx_deployments_env ON deployments(environment);
