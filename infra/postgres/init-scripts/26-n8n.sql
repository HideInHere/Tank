-- n8n workflow orchestration DB setup
-- n8n manages its own schema; this creates the DB and grants permissions
\c postgres

SELECT 'CREATE DATABASE n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec

\c n8n
-- Grant permissions (n8n will create its own tables on first start)
-- This file ensures the database exists before n8n starts
CREATE TABLE IF NOT EXISTS tank_workflow_log (
    id BIGSERIAL PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    execution_id TEXT,
    status TEXT,
    data JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_wf_log_name ON tank_workflow_log(workflow_name);
CREATE INDEX IF NOT EXISTS idx_wf_log_status ON tank_workflow_log(status);
