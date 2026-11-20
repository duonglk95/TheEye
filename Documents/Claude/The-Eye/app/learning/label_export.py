"""
Dữ liệu cho "giáo viên LLM" bên ngoài — Bot KHÔNG gọi LLM.

Một Scheduled Task của Claude Code (chạy bằng gói Claude của chủ bot, không dùng API key)
mỗi tuần gọi 2 endpoint trong app/web/api.py:
  GET  /api/labeling/pending  → fetch_pending(): tin chưa có nhãn + hướng dẫn chấm
  POST /api/labeling/labels   → import_labels(): lưu nhãn vào training_labels (labeler="llm:…")
Lần tự học kế tiếp dùng các nhãn này với trọng số thấp hơn nhãn người chấm, cao hơn nhãn từ khoá.
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import ArticleContent, ArticleMeta, Company, TrainingLabel
from app.learning.feedback import HUMAN_PREFIX

LLM_PREFIX = "llm:"
DEFAULT_LLM_LABELER = "llm:claude-task"
VN_TZ = timezone(timedelta(hours=7))
MAX_ARTICLES = 150
CONTENT_EXCERPT = 1200
VALID = {"POS", "NEU", "NEG"}

INSTRUCTIONS = """Bạn là chuyên viên phân tích tin doanh nghiệp niêm yết Việt Nam.
Với MỖI bài, đánh giá tin đó tốt hay xấu cho cổ đông của công ty được nêu (ticker):
- POS: tin tốt — lợi nhuận/doanh thu tăng, hợp đồng lớn, mở rộng, được khen thưởng/vinh danh, cổ tức cao...
- NEG: tin xấu — thua lỗ, bị phạt/điều tra/khởi tố, nợ xấu, mất hợp đồng, lãnh đạo vướng pháp lý...
- NEU: trung tính — thông báo hành chính, lịch họp, giao dịch cổ đông thông thường, tin chung chung,
  hoặc bài không thực sự nói về công ty đó.
Đọc cả nội dung trích, không chỉ tiêu đề (VD tiêu đề "nhận Huân chương" nhưng nội dung toàn tin tốt → POS).
Chấm đủ mọi bài. Lý do ngắn gọn, ≤ 15 từ, tiếng Việt."""


def _clean(text: str | None, limit: int | None = None) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t


async def fetch_pending(days: int = 7, limit: int = MAX_ARTICLES) -> list[dict]:
    """Tin trong `days` ngày, chưa có nhãn người chấm / LLM; tin Bao kém chắc nhất lên đầu."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with AsyncSessionLocal() as session:
        labeled = select(TrainingLabel.article_id).where(
            TrainingLabel.labeler.like(f"{HUMAN_PREFIX}%") | TrainingLabel.labeler.like(f"{LLM_PREFIX}%")
        )
        rows = await session.execute(
            select(ArticleMeta, Company, func.left(ArticleContent.content_raw, CONTENT_EXCERPT + 200))
            .join(Company, ArticleMeta.company_id == Company.id)
            .outerjoin(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.id.not_in(labeled))
            .order_by(func.coalesce(ArticleMeta.sentiment_score, 0).asc(), ArticleMeta.published_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": art.id,
                "ticker": company.ticker,
                "company": _clean(company.name),
                "published": art.published_at.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M"),
                "title": _clean(art.title),
                "summary": _clean(art.summary, 400),
                "content": _clean(content, CONTENT_EXCERPT),
            }
            for art, company, content in rows.all()
        ]


def validate_labels(items) -> tuple[dict[int, str], list[str]]:
    """[{id, label, reason?}] → ({id: label}, lỗi). Bỏ mục sai định dạng, không làm hỏng cả lô."""
    out, errors = {}, []
    if not isinstance(items, list):
        return {}, ["labels phải là danh sách"]
    for i, it in enumerate(items):
        try:
            aid, label = int(it["id"]), str(it["label"]).strip().upper()
        except (KeyError, TypeError, ValueError):
            errors.append(f"mục {i}: thiếu id/label")
            continue
        if label not in VALID:
            errors.append(f"mục {i} (id {aid}): nhãn '{label}' không hợp lệ")
            continue
        out[aid] = label
    return out, errors


async def import_labels(labels: dict[int, str], labeler: str = DEFAULT_LLM_LABELER) -> dict:
    """Lưu nhãn LLM. Bỏ qua id không tồn tại. Gửi lại cùng bài → ghi đè nhãn cũ của labeler đó."""
    if not labeler.startswith(LLM_PREFIX):
        labeler = LLM_PREFIX + labeler
    labeler = labeler[:50]
    if not labels:
        return {"saved": 0, "unknown_ids": [], "by_label": {}}
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        existing = set((await session.scalars(
            select(ArticleMeta.id).where(ArticleMeta.id.in_(list(labels)))
        )).all())
        by_label: dict[str, int] = {}
        for aid in existing:
            label = labels[aid]
            stmt = pg_insert(TrainingLabel).values(
                article_id=aid, label=label, labeler=labeler, confidence=0.8, created_at=now,
            )
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["article_id", "labeler"], set_={"label": label, "created_at": now},
            ))
            by_label[label] = by_label.get(label, 0) + 1
        await session.commit()
    return {"saved": len(existing), "unknown_ids": sorted(set(labels) - existing), "by_label": by_label}
