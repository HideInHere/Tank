-- feed-aggregator schema (uses research DB)
\c research

CREATE TABLE IF NOT EXISTS data_feeds (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL UNIQUE,
    feed_type TEXT NOT NULL CHECK (feed_type IN ('price','news','social','economic','order_book')),
    source_url TEXT,
    active BOOLEAN DEFAULT true,
    poll_interval_seconds INTEGER DEFAULT 60,
    last_polled TIMESTAMPTZ,
    error_count INTEGER DEFAULT 0,
    config JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS raw_feed_data (
    id BIGSERIAL PRIMARY KEY,
    feed_id UUID REFERENCES data_feeds(id),
    raw_content JSONB NOT NULL,
    processed BOOLEAN DEFAULT false,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    headline TEXT NOT NULL,
    source TEXT,
    url TEXT,
    symbols TEXT[],
    sentiment FLOAT,
    published_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT NOW()
);

-- Default feeds
INSERT INTO data_feeds (name, feed_type, poll_interval_seconds) VALUES
    ('mock-price-feed', 'price', 30),
    ('mock-news-feed', 'news', 300)
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_raw_feed_processed ON raw_feed_data(processed) WHERE processed = false;
CREATE INDEX IF NOT EXISTS idx_news_symbols ON news_items USING GIN(symbols);
CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at DESC);
