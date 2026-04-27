-- meta-builder schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS build_artifacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('docker_image','config','schema','script','report')),
    name TEXT NOT NULL,
    version TEXT,
    hash TEXT,
    storage_path TEXT,
    metadata JSONB DEFAULT '{}',
    built_by TEXT,
    built_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    priority INTEGER DEFAULT 5,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    result JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_build_artifacts_type ON build_artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_system_tasks_status ON system_tasks(status);
CREATE INDEX IF NOT EXISTS idx_system_tasks_scheduled ON system_tasks(scheduled_at);
