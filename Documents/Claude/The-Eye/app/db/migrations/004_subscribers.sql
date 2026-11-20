-- Bảng subscribers trước đây chỉ khai báo trong models.py, chưa có migration.
-- IF NOT EXISTS: DB đã có bảng (tạo tay) thì không đổi gì.
CREATE TABLE IF NOT EXISTS subscribers (
    id             SERIAL PRIMARY KEY,
    chat_id        BIGINT UNIQUE NOT NULL,
    username       VARCHAR(100),
    first_name     VARCHAR(100),
    tickers        VARCHAR(10)[],
    sentiments     VARCHAR(5)[] DEFAULT ARRAY['NEG'],
    active         BOOLEAN DEFAULT TRUE,
    subscribed_at  TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at   TIMESTAMPTZ
);
