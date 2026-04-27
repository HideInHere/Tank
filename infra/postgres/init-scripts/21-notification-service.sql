-- notification-service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    recipient TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('telegram','email','webhook','slack','sms')),
    title TEXT,
    message TEXT NOT NULL,
    payload JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
    retry_count INTEGER DEFAULT 0,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    error_msg TEXT
);

CREATE TABLE IF NOT EXISTS notification_templates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    subject_template TEXT,
    body_template TEXT NOT NULL,
    variables TEXT[],
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS notification_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    config JSONB DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    UNIQUE(user_id, event_type, channel)
);

CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_notifications_scheduled ON notifications(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient);
