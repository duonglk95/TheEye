"""
Classifier facade — ưu tiên PhoBERT nếu có model, fallback sang rule-based.
Ghi kết quả vào article_meta.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta
from app.config import load_sentiment

log = logging.getLogger(__name__)


def _do_classify(title: str, summary: str | None, cfg: dict) -> tuple[str, float, str]:
    model_path = cfg.get("model_path")
    threshold = cfg.get("phobert_confidence_threshold", 0.75)

    if model_path:
        try:
            from app.classifier.phobert import classify as phobert_classify
            label, score, method = phobert_classify(title, summary, model_path)
            if score >= threshold:
                return label, score, method
            log.debug(f"PhoBERT low confidence ({score:.2f}), falling back to rules")
        except ImportError as e:
            log.warning(f"PhoBERT unavailable: {e}")

    from app.classifier.rule_based import classify as rule_classify
    return rule_classify(title, summary)


async def classify_article(article_id: int) -> tuple[str, float, str] | None:
    """Classify 1 article và lưu kết quả vào DB. Trả về (label, score, method)."""
    cfg = load_sentiment()

    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if not article:
            return None

        # Bỏ qua nếu đã classify
        if article.sentiment:
            return article.sentiment, article.sentiment_score, article.sentiment_method

        label, score, method = _do_classify(article.title, article.summary, cfg)
        now = datetime.now(timezone.utc)

        article.sentiment = label
        article.sentiment_score = score
        article.sentiment_method = method
        article.classified_at = now

        await session.commit()
        log.debug(f"classified #{article_id}: {label} ({score:.2f}) via {method}")
        return label, score, method


async def classify_batch(article_ids: list[int]) -> dict[int, str]:
    """Classify nhiều articles, trả về {article_id: label}."""
    cfg = load_sentiment()
    results = {}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta)
            .where(ArticleMeta.id.in_(article_ids))
            .where(ArticleMeta.sentiment == None)  # noqa: E711
        )
        articles = result.scalars().all()

        now = datetime.now(timezone.utc)
        for article in articles:
            label, score, method = _do_classify(article.title, article.summary, cfg)
            article.sentiment = label
            article.sentiment_score = score
            article.sentiment_method = method
            article.classified_at = now
            results[article.id] = label

        await session.commit()

    log.info(f"classify_batch: {len(results)}/{len(article_ids)} classified")
    return results
