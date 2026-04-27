-- market-data service schema (uses tank DB)
\c tank

CREATE TABLE IF NOT EXISTS market_ticks (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    price NUMERIC(18,8) NOT NULL,
    bid NUMERIC(18,8),
    ask NUMERIC(18,8),
    volume BIGINT DEFAULT 0,
    source TEXT,
    tick_time TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ohlcv (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('1m','5m','15m','1h','4h','1d','1w')),
    open NUMERIC(18,8),
    high NUMERIC(18,8),
    low NUMERIC(18,8),
    close NUMERIC(18,8),
    volume BIGINT,
    candle_time TIMESTAMPTZ NOT NULL,
    UNIQUE(symbol, timeframe, candle_time)
);

CREATE TABLE IF NOT EXISTS market_status (
    symbol TEXT PRIMARY KEY,
    last_price NUMERIC(18,8),
    price_change_24h FLOAT,
    volume_24h BIGINT,
    high_24h NUMERIC(18,8),
    low_24h NUMERIC(18,8),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_ticks_symbol ON market_ticks(symbol);
CREATE INDEX IF NOT EXISTS idx_market_ticks_time ON market_ticks(tick_time DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf ON ohlcv(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_ohlcv_time ON ohlcv(candle_time DESC);
