"""
Phase 2 — Auto-labeling bằng Claude Haiku.

Pipeline:
  1. Fetch bài từ article_meta + article_content chưa có training label
  2. Gọi Claude Haiku theo batch → label (NEU/POS/NEG) + category + confidence
  3. Lưu vào training_labels với labeler="haiku-3-5"

Usage:
  python -m training.label_with_claude [--limit 500] [--dry-run]

Cost estimate (Haiku 3.5):
  ~150 tokens/bài × 5000 bài = 750K tokens ≈ $0.09 input + $0.18 output ≈ ~$0.27
"""
import asyncio
import json
import logging
import os
import sys
import argparse
from datetime import datetime, timezone

import anthropic
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, ArticleContent, Company, TrainingLabel
from app.config import load_sentiment

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

LABELER_NAME = "haiku-3-5"
BATCH_SIZE = 10   # articles per API call (dùng Haiku batch)

SYSTEM_PROMPT = """\
Bạn là chuyên gia phân tích tin tức tài chính và doanh nghiệp Việt Nam.
Nhiệm vụ: phân loại cảm xúc (sentiment) của mỗi bài báo đối với công ty được đề cập.

NHÃN:
- POS: tin tích cực — lợi nhuận tăng, ký kết hợp đồng, mở rộng, IPO thành công, v.v.
- NEG: tin tiêu cực — thua lỗ, khởi tố, vi phạm, nợ xấu, cắt giảm nhân sự, v.v.
- NEU: tin trung lập — thông báo, họp ĐHCĐ, bổ nhiệm thông thường, báo cáo không rõ xu hướng.

DANH MỤC (category):
- chung_khoan: giao dịch, biến động giá, khối ngoại
- bao_cao_tai_chinh: KQKD, doanh thu, lợi nhuận, BCTC
- hoat_dong_su_kien: ký kết, ra mắt, khai trương, hội nghị, hợp tác
- nhan_su: bổ nhiệm, miễn nhiệm, thay đổi lãnh đạo
- phap_ly: điều tra, khởi tố, vi phạm, phán quyết, tranh chấp
- chien_luoc: M&A, thoái vốn, IPO, mở rộng, liên kết chiến lược
- san_xuat_kinh_doanh: hoạt động vận hành, đơn hàng, hợp đồng, nhà máy
- vi_mo: chính sách ngành, quy định ảnh hưởng gián tiếp

Trả về JSON array với đúng số phần tử bằng số bài đầu vào:
[
  {
    "id": <article_id>,
    "label": "POS" | "NEG" | "NEU",
    "category": "<category_id>",
    "confidence": <0.0-1.0>,
    "reason": "<giải thích ngắn gọn 1 câu bằng tiếng Việt>"
  },
  ...
]
"""


def _build_user_prompt(articles: list[dict]) -> str:
    lines = [f"Phân loại {len(articles)} bài báo sau:\n"]
    for art in articles:
        text = f"Công ty: [{art['ticker']}] {art['company_name']}\n"
        text += f"Tiêu đề: {art['title']}\n"
        if art.get("summary"):
            text += f"Tóm tắt: {art['summary'][:300]}\n"
        if art.get("content"):
            text += f"Nội dung (rút gọn): {art['content'][:500]}\n"
        lines.append(f"--- ID: {art['id']} ---\n{text}")
    return "\n".join(lines)


async def _fetch_unlabeled(session, limit: int) -> list[dict]:
    """Fetch bài chưa có label từ Haiku."""
    result = await session.execute(
        select(ArticleMeta, Company, ArticleContent)
        .join(Company, ArticleMeta.company_id == Company.id)
        .outerjoin(ArticleContent, ArticleMeta.id == ArticleContent.article_id)
        .outerjoin(
            TrainingLabel,
            (TrainingLabel.article_id == ArticleMeta.id) &
            (TrainingLabel.labeler == LABELER_NAME),
        )
        .where(TrainingLabel.id == None)     # noqa: E711  — chưa có label Haiku
        .where(ArticleMeta.sentiment != None)  # noqa: E711  — đã qua rule classifier
        .order_by(ArticleMeta.published_at.desc())
        .limit(limit)
    )
    rows = result.fetchall()

    articles = []
    for meta, company, content in rows:
        articles.append({
            "id": meta.id,
            "ticker": company.ticker,
            "company_name": company.name,
            "title": meta.title,
            "summary": meta.summary or "",
            "content": content.content_raw[:500] if content and content.content_raw else "",
        })
    return articles


async def _label_batch(
    client: anthropic.AsyncAnthropic,
    articles: list[dict],
    dry_run: bool,
) -> list[dict]:
    """Gửi 1 batch lên Haiku, trả về list kết quả."""
    if dry_run:
        # Simulate response
        return [
            {
                "id": art["id"],
                "label": ["POS", "NEG", "NEU"][i % 3],
                "category": "bao_cao_tai_chinh",
                "confidence": 0.82,
                "reason": "[DRY RUN] Simulated label",
            }
            for i, art in enumerate(articles)
        ]

    try:
        msg = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_prompt(articles)}],
        )
        raw = msg.content[0].text.strip()

        # Extract JSON array từ response
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON array in response: {raw[:200]}")

        results = json.loads(raw[start:end])
        log.info(
            f"  Batch {len(articles)} bài | "
            f"input={msg.usage.input_tokens} output={msg.usage.output_tokens} tokens"
        )
        return results

    except Exception as e:
        log.error(f"  Haiku batch failed: {e}")
        return []


async def _save_labels(session, results: list[dict]) -> int:
    """Lưu kết quả vào training_labels."""
    saved = 0
    for r in results:
        try:
            stmt = (
                pg_insert(TrainingLabel)
                .values(
                    article_id=r["id"],
                    label=r["label"],
                    category=r.get("category"),
                    labeler=LABELER_NAME,
                    confidence=r.get("confidence"),
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing()
            )
            await session.execute(stmt)
            saved += 1
        except Exception as e:
            log.warning(f"  Save label failed for id={r.get('id')}: {e}")
    await session.commit()
    return saved


async def run(limit: int = 500, dry_run: bool = False):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not dry_run:
        raise ValueError("ANTHROPIC_API_KEY not set. Add to .env")

    client = anthropic.AsyncAnthropic(api_key=api_key or "dummy")

    async with AsyncSessionLocal() as session:
        articles = await _fetch_unlabeled(session, limit)

    if not articles:
        log.info("Không có bài nào cần label.")
        return

    log.info(f"Cần label: {len(articles)} bài | batch_size={BATCH_SIZE} | dry_run={dry_run}")
    log.info(f"Model: claude-haiku-4-5 | labeler: {LABELER_NAME}")

    total_saved = 0
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        log.info(f"Batch {i // BATCH_SIZE + 1}/{(len(articles) - 1) // BATCH_SIZE + 1} ({len(batch)} bài)...")

        results = await _label_batch(client, batch, dry_run)

        if results:
            async with AsyncSessionLocal() as session:
                saved = await _save_labels(session, results)
                total_saved += saved
            log.info(f"  → Saved {saved}/{len(batch)} labels")

        # Rate limiting: 0.5s giữa các batch
        if not dry_run:
            await asyncio.sleep(0.5)

    log.info(f"\n✅ Hoàn tất! Đã label {total_saved}/{len(articles)} bài")
    log.info(f"   → Xem kết quả: SELECT label, category, COUNT(*) FROM training_labels WHERE labeler='{LABELER_NAME}' GROUP BY 1,2;")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-label articles with Claude Haiku")
    parser.add_argument("--limit",   type=int, default=500, help="Số bài tối đa (default: 500)")
    parser.add_argument("--dry-run", action="store_true",   help="Không gọi API, chỉ simulate")
    args = parser.parse_args()
    asyncio.run(run(limit=args.limit, dry_run=args.dry_run))
