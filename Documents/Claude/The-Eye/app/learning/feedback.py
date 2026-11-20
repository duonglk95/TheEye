"""
Phản hồi của người dùng — "giáo viên" chính của bot.

Mỗi lần ai đó bấm nút ✅/🟢/🔴/⚪ dưới tin hoặc gõ /fix:
  - Lưu vào training_labels với labeler = "human:<telegram_user_id>"
  - Cập nhật luôn nhãn của bài (method = "human", không bị mô hình ghi đè)
Lần train kế tiếp, các nhãn này có trọng số cao nhất và là thước đo chính để
đánh giá mô hình mới có giỏi hơn mô hình cũ không.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, TrainingLabel

log = logging.getLogger(__name__)

HUMAN_PREFIX = "human:"
VALID = {"POS", "NEG", "NEU"}


async def record_feedback(
    article_id: int, label: str, user_id: int, username: str | None = None, rating: int | None = None,
) -> ArticleMeta | None:
    """Ghi nhận nhãn đúng cho 1 bài. Trả về bài (đã cập nhật) hoặc None nếu không có bài."""
    label = label.upper()
    if label not in VALID:
        raise ValueError(f"Nhãn không hợp lệ: {label}")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if article is None:
            return None

        stmt = pg_insert(TrainingLabel).values(
            article_id=article_id, label=label, labeler=f"{HUMAN_PREFIX}{user_id}",
            confidence=1.0, created_at=now, rating=rating,
        )
        await session.execute(stmt.on_conflict_do_update(
            index_elements=["article_id", "labeler"],
            set_={"label": label, "created_at": now, "rating": rating},
        ))

        evidence = dict(article.sentiment_evidence or {})
        if article.sentiment_method == "human" and "human" in evidence:
            # Đã có người xác nhận trước đó → giữ nguyên nhãn gốc bot đoán
            previous = evidence["human"].get("previous")
            evidence["human"] = {**evidence["human"], "by": username or str(user_id)}
        else:
            previous = article.sentiment
            evidence["human"] = {"by": username or str(user_id), "previous": previous,
                                 "previous_method": article.sentiment_method,
                                 "previous_score": article.sentiment_score}
        article.sentiment = label
        article.sentiment_score = 1.0
        article.sentiment_method = "human"
        article.sentiment_evidence = evidence
        article.classified_at = now
        await session.commit()

    log.info(f"[feedback] #{article_id}: {previous} → {label} by {username or user_id}")
    return article
