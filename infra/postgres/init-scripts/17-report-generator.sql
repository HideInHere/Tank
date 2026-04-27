-- report-generator schema (uses ledger DB)
\c ledger

CREATE TABLE IF NOT EXISTS reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_type TEXT NOT NULL CHECK (report_type IN ('daily','weekly','monthly','on_demand','backtest')),
    title TEXT NOT NULL,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','generating','completed','failed')),
    format TEXT DEFAULT 'json' CHECK (format IN ('json','csv','pdf','html')),
    data JSONB DEFAULT '{}',
    file_path TEXT,
    generated_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS report_schedules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    report_type TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    active BOOLEAN DEFAULT true,
    last_run TIMESTAMPTZ,
    next_run TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(report_type);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
