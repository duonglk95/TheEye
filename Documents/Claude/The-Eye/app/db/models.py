from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, Float, ForeignKey,
    Integer, LargeBinary, String, Text, TIMESTAMP, ARRAY, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.dialects.postgresql import JSONB


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), unique=True, nullable=False)
    name = Column(Text, nullable=False)
    full_name = Column(Text)
    aliases = Column(ARRAY(Text), default=[])
    keywords = Column(ARRAY(Text), default=[])
    sector = Column(String(100))
    exchange = Column(String(20))
    active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    articles = relationship("ArticleMeta", back_populates="company")
    stock_data = relationship("StockDaily", back_populates="company")


class FeedSource(Base):
    __tablename__ = "feed_sources"

    id = Column(Integer, primary_key=True)
    source_id = Column(String(100), unique=True, nullable=False)  # yaml id
    name = Column(String(200))
    url = Column(Text, unique=True, nullable=False)
    type = Column(String(20))       # rss | google_rss | api
    priority = Column(String(10))   # high | medium | low
    poll_interval_sec = Column(Integer, default=300)
    active = Column(Boolean, default=True)
    last_polled_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    articles = relationship("ArticleMeta", back_populates="source")


class ArticleMeta(Base):
    """Tầng nhẹ — Phase 1 đọc bảng này để classify & notify."""
    __tablename__ = "article_meta"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    url = Column(Text, unique=True, nullable=False)
    title = Column(Text, nullable=False)
    summary = Column(Text)              # từ RSS feed (không cần scrape)
    source_id = Column(Integer, ForeignKey("feed_sources.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))
    published_at = Column(TIMESTAMP(timezone=True), nullable=False)
    fetched_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    # Classification
    sentiment = Column(String(5))       # NEU | POS | NEG
    sentiment_score = Column(Float)
    sentiment_method = Column(String(30))   # rule_v1 | phobert_v1 | ...
    classified_at = Column(TIMESTAMP(timezone=True))
    sentiment_evidence = Column(JSONB)      # {"phrases": [...], "probs": {...}, "calibrated": bool}
    read_depth = Column(String(10))         # headline (tiêu đề+sapo) | full (đã đọc thân bài)

    # Notification
    notified = Column(Boolean, default=False)
    notified_at = Column(TIMESTAMP(timezone=True))

    source = relationship("FeedSource", back_populates="articles")
    company = relationship("Company", back_populates="articles")
    content = relationship("ArticleContent", back_populates="article", uselist=False)
    training_labels = relationship("TrainingLabel", back_populates="article")


class ArticleContent(Base):
    """Tầng đầy đủ — Phase 2 training & Phase 3 analytics."""
    __tablename__ = "article_content"

    article_id = Column(BigInteger, ForeignKey("article_meta.id"), primary_key=True)
    content_raw = Column(Text)          # full text đã strip HTML
    content_html = Column(Text)         # raw HTML nếu cần
    word_count = Column(Integer)
    scraped_at = Column(TIMESTAMP(timezone=True))
    scrape_error = Column(Text)         # null nếu thành công

    article = relationship("ArticleMeta", back_populates="content")


class TrainingLabel(Base):
    """Dataset cho Phase 2 — PhoBERT training."""
    __tablename__ = "training_labels"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    article_id = Column(BigInteger, ForeignKey("article_meta.id"), nullable=False)
    label = Column(String(5), nullable=False)       # NEU | POS | NEG
    category = Column(String(50))                   # từ training_categories trong sentiment.yaml
    labeler = Column(String(50))                    # manual | rule_v1 | phobert_v1
    confidence = Column(Float)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    article = relationship("ArticleMeta", back_populates="training_labels")


class StockDaily(Base):
    """Phase 3 — dữ liệu chứng khoán từ vnstock."""
    __tablename__ = "stock_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    ticker = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    close = Column(Float)
    high = Column(Float)
    low = Column(Float)
    volume = Column(BigInteger)
    foreign_buy_vol = Column(BigInteger)
    foreign_sell_vol = Column(BigInteger)
    extra = Column(JSONB)   # dữ liệu bổ sung từ vnstock nếu có

    company = relationship("Company", back_populates="stock_data")


class Subscriber(Base):
    """
    Người dùng đã /subscribe — nhận push notification vào chat riêng.
    Mỗi subscriber có thể lọc theo tickers cụ thể.
    """
    __tablename__ = "subscribers"

    id          = Column(Integer, primary_key=True)
    chat_id     = Column(BigInteger, unique=True, nullable=False)  # Telegram chat_id
    username    = Column(String(100))                              # @username (tuỳ chọn)
    first_name  = Column(String(100))
    # tickers = None → nhận tất cả; ["VIC","SBT"] → chỉ nhận ticker đó
    tickers     = Column(ARRAY(String(10)), nullable=True)
    # loại tin nhận: ["POS","NEG"] hoặc ["NEG"] hoặc ["POS","NEG","NEU"]
    sentiments  = Column(ARRAY(String(5)), default=["NEG"])
    active      = Column(Boolean, default=True)
    subscribed_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    last_seen_at  = Column(TIMESTAMP(timezone=True))


# Index declarations (được tạo qua migration)
# CREATE INDEX idx_article_meta_company_pub   ON article_meta(company_id, published_at DESC);
# CREATE INDEX idx_article_meta_notified      ON article_meta(notified) WHERE notified = FALSE;
# CREATE INDEX idx_article_meta_sentiment     ON article_meta(sentiment, published_at DESC);
# CREATE INDEX idx_stock_daily_ticker_date    ON stock_daily(ticker, date);
# CREATE UNIQUE INDEX uq_stock_daily          ON stock_daily(ticker, date);


class MLModel(Base):
    """Mô hình ML đã train — lưu trong DB vì filesystem Railway bị xoá mỗi lần deploy."""
    __tablename__ = "ml_models"

    id         = Column(Integer, primary_key=True)
    version    = Column(Integer, unique=True, nullable=False)
    status     = Column(String(20), nullable=False)   # active | rejected | retired
    algo       = Column(String(50), nullable=False)
    n_train    = Column(Integer)
    n_gold     = Column(Integer)
    metrics    = Column(JSONB)
    blob       = Column(LargeBinary)
    note       = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
