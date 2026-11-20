"""
Classifier facade — một điểm vào cho mọi lần phân loại.

Thứ tự ưu tiên:
  1. Nhãn người dùng xác nhận (method="human") — không bao giờ bị ghi đè
  2. Mô hình ML tự học (ml_vN) — % đã hiệu chỉnh trên dữ liệu kiểm định
  3. PhoBERT (nếu cấu hình model_path, tuỳ chọn)
  4. Rule-based — % là ước lượng Laplace, CHƯA hiệu chỉnh

Hai lượt đọc:
  - classify_batch(): ngay khi lấy RSS, chỉ có tiêu đề + sapo (read_depth="headline")
  - deep_read_pending(): sau khi scraper lấy được thân bài → đọc lại toàn bài (read_depth="full")
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.classifier import model_store
from app.classifier.ml_model import LABELS, build_text
from app.classifier.rule_based import read_article, top_phrases
from app.config import load_sentiment
from app.db import AsyncSessionLocal
from app.db.models import ArticleContent, ArticleMeta

log = logging.getLogger(__name__)


@dataclass
class Prediction:
    label: str
    score: float
    method: str
    calibrated: bool
    phrases: list[str] = field(default_factory=list)
    probs: dict[str, float] = field(default_factory=dict)
    body_stats: dict = field(default_factory=dict)

    def evidence(self) -> dict:
        return {
            "phrases": self.phrases,
            "probs": self.probs,
            "calibrated": self.calibrated,
            **({"body": self.body_stats} if self.body_stats else {}),
        }


def predict(title: str, summary: str | None, content: str | None = None) -> Prediction:
    """Phân loại 1 bài (đồng bộ, không đụng DB)."""
    reading = read_article(title, summary, content)
    rule_hits = {
        "POS": sum(1 for l, _, _ in reading.evidence.hits if l == "POS"),
        "NEG": sum(1 for l, _, _ in reading.evidence.hits if l == "NEG"),
    }
    body_stats = (
        {"sentences": reading.body_sentences, "pos": reading.body_pos_sentences, "neg": reading.body_neg_sentences}
        if reading.body_sentences else {}
    )

    bundle = model_store.get_active()
    if bundle is not None:
        try:
            text = build_text(title, summary, content, rule_hits)
            probs = bundle.predict_proba([text])[0]
            idx = int(probs.argmax())
            label = LABELS[idx]
            return Prediction(
                label=label,
                score=round(float(probs[idx]), 3),
                method=f"ml_v{bundle.version}" + ("+full" if content else ""),
                calibrated=True,
                phrases=_merge_phrases(
                    top_phrases(reading.evidence, label, k=3), bundle.explain(text, label)
                ) if label != "NEU" else [],
                probs={l: round(float(p), 3) for l, p in zip(LABELS, probs)},
                body_stats=body_stats,
            )
        except Exception as e:
            log.error(f"ML predict failed, fallback to rules: {e}")

    cfg = load_sentiment()
    if cfg.get("model_path"):
        try:
            from app.classifier.phobert import classify as phobert_classify
            label, score, method = phobert_classify(title, summary, cfg["model_path"])
            if score >= cfg.get("phobert_confidence_threshold", 0.75):
                return Prediction(label, score, method, calibrated=False)
        except ImportError as e:
            log.warning(f"PhoBERT unavailable: {e}")

    return Prediction(
        label=reading.label,
        score=reading.score,
        method=reading.method,
        calibrated=False,
        phrases=top_phrases(reading.evidence, reading.label) if reading.label != "NEU" else [],
        body_stats=body_stats,
    )


def _merge_phrases(rule: list[str], learned: list[str], k: int = 5) -> list[str]:
    """Từ khoá luật trước (dễ hiểu), sau đó cụm mô hình tự học; bỏ trùng / cụm con."""
    out: list[str] = []
    for p in rule + learned:
        if any(p in o or o in p for o in out):
            continue
        out.append(p)
    return out[:k]


def _apply(article: ArticleMeta, pred: Prediction, depth: str) -> None:
    article.sentiment = pred.label
    article.sentiment_score = pred.score
    article.sentiment_method = pred.method[:30]
    article.sentiment_evidence = pred.evidence()
    article.read_depth = depth
    article.classified_at = datetime.now(timezone.utc)


async def classify_article(article_id: int) -> tuple[str, float, str] | None:
    """Classify 1 article (nếu chưa) và lưu. Trả về (label, score, method)."""
    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if not article:
            return None
        if not article.sentiment:
            _apply(article, predict(article.title, article.summary), "headline")
            await session.commit()
        return article.sentiment, article.sentiment_score, article.sentiment_method


async def classify_batch(article_ids: list[int]) -> dict[int, str]:
    """Lượt đọc nhanh (tiêu đề + sapo) cho bài mới. Trả về {article_id: label}."""
    results = {}
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta)
            .where(ArticleMeta.id.in_(article_ids))
            .where(ArticleMeta.sentiment == None)  # noqa: E711
        )
        for article in result.scalars().all():
            pred = predict(article.title, article.summary)
            _apply(article, pred, "headline")
            results[article.id] = pred.label
        await session.commit()

    log.info(f"classify_batch: {len(results)}/{len(article_ids)} classified")
    return results


@dataclass
class Change:
    article_id: int
    old: str | None
    new: str
    notified: bool


async def deep_read_pending(limit: int = 50, max_age_hours: int = 72) -> list[Change]:
    """
    Đọc lại toàn bài cho các bài đã scrape được nội dung nhưng mới chỉ đọc tiêu đề.
    Trả về danh sách bài có nhãn thay đổi (VD NEU → POS khi thân bài toàn tin tốt).
    """
    since = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    changes: list[Change] = []
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, ArticleContent.content_raw)
            .join(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
            .where(ArticleContent.scraped_at != None)          # noqa: E711
            .where(ArticleContent.content_raw != None)         # noqa: E711
            .where((ArticleMeta.read_depth == None) | (ArticleMeta.read_depth != "full"))  # noqa: E711
            .where((ArticleMeta.sentiment_method == None) | ArticleMeta.sentiment_method.not_in(("human", "llm")))  # noqa: E711
            .where(ArticleMeta.fetched_at >= since)
            .order_by(ArticleMeta.published_at.desc())
            .limit(limit)
        )
        for article, content in result.all():
            old = article.sentiment
            pred = predict(article.title, article.summary, content)
            _apply(article, pred, "full")
            if old != pred.label:
                changes.append(Change(article.id, old, pred.label, bool(article.notified)))
        await session.commit()

    if changes:
        log.info("deep_read: " + ", ".join(f"#{c.article_id} {c.old}→{c.new}" for c in changes))
    return changes
