-- Migration 001: Initial schema
-- Run: psql $DATABASE_URL < app/db/migrations/001_init.sql

CREATE TABLE IF NOT EXISTS companies (
    id          SERIAL PRIMARY KEY,
    ticker      VARCHAR(10) UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    full_name   TEXT,
    aliases     TEXT[] DEFAULT '{}',
    keywords    TEXT[] DEFAULT '{}',
    sector      VARCHAR(100),
    exchange    VARCHAR(20),
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feed_sources (
    id                  SERIAL PRIMARY KEY,
    source_id           VARCHAR(100) UNIQUE NOT NULL,
    name                VARCHAR(200),
    url                 TEXT UNIQUE NOT NULL,
    type                VARCHAR(20),
    priority            VARCHAR(10),
    poll_interval_sec   INT DEFAULT 300,
    active              BOOLEAN DEFAULT TRUE,
    last_polled_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS article_meta (
    id                  BIGSERIAL PRIMARY KEY,
    url                 TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    summary             TEXT,
    source_id           INT REFERENCES feed_sources(id),
    company_id          INT REFERENCES companies(id),
    published_at        TIMESTAMPTZ NOT NULL,
    fetched_at          TIMESTAMPTZ DEFAULT NOW(),
    sentiment           VARCHAR(5),
    sentiment_score     FLOAT,
    sentiment_method    VARCHAR(30),
    classified_at       TIMESTAMPTZ,
    notified            BOOLEAN DEFAULT FALSE,
    notified_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS article_content (
    article_id      BIGINT PRIMARY KEY REFERENCES article_meta(id),
    content_raw     TEXT,
    content_html    TEXT,
    word_count      INT,
    scraped_at      TIMESTAMPTZ,
    scrape_error    TEXT
);

CREATE TABLE IF NOT EXISTS training_labels (
    id          BIGSERIAL PRIMARY KEY,
    article_id  BIGINT NOT NULL REFERENCES article_meta(id),
    label       VARCHAR(5) NOT NULL,
    category    VARCHAR(50),
    labeler     VARCHAR(50),
    confidence  FLOAT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(article_id, labeler)
);

CREATE TABLE IF NOT EXISTS stock_daily (
    id                  BIGSERIAL PRIMARY KEY,
    company_id          INT REFERENCES companies(id),
    ticker              VARCHAR(10) NOT NULL,
    date                DATE NOT NULL,
    open                FLOAT,
    close               FLOAT,
    high                FLOAT,
    low                 FLOAT,
    volume              BIGINT,
    foreign_buy_vol     BIGINT,
    foreign_sell_vol    BIGINT,
    extra               JSONB,
    UNIQUE(ticker, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_article_meta_company_pub
    ON article_meta(company_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_article_meta_notified
    ON article_meta(notified) WHERE notified = FALSE;

CREATE INDEX IF NOT EXISTS idx_article_meta_sentiment
    ON article_meta(sentiment, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_stock_daily_ticker_date
    ON stock_daily(ticker, date);
