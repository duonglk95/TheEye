-- Self-learning: đọc toàn bài, lưu bằng chứng, lưu mô hình ML trong DB

ALTER TABLE article_meta ADD COLUMN IF NOT EXISTS sentiment_evidence JSONB;
ALTER TABLE article_meta ADD COLUMN IF NOT EXISTS read_depth VARCHAR(10);   -- headline | full

CREATE TABLE IF NOT EXISTS ml_models (
    id          SERIAL PRIMARY KEY,
    version     INT NOT NULL UNIQUE,
    status      VARCHAR(20) NOT NULL,          -- active | rejected | retired
    algo        VARCHAR(50) NOT NULL,
    n_train     INT,
    n_gold      INT,
    metrics     JSONB,
    blob        BYTEA,
    note        TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_models_status ON ml_models(status);
CREATE INDEX IF NOT EXISTS idx_training_labels_labeler ON training_labels(labeler);
CREATE INDEX IF NOT EXISTS idx_article_meta_read_depth ON article_meta(read_depth);
