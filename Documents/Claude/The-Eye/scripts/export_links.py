"""
Export bài báo ra file CSV để tracking local.

Cách dùng:
  python scripts/export_links.py                  # 7 ngày gần nhất
  python scripts/export_links.py 168              # 168 giờ (= 7 ngày)
  python scripts/export_links.py 24               # 24 giờ gần nhất
  python scripts/export_links.py 168 output.csv   # chỉ định tên file

Output CSV (UTF-8 BOM — mở được bằng Excel):
  ticker | company | sentiment | score | published_at | title | url

Yêu cầu: file .env với DATABASE_URL và TELEGRAM_BOT_TOKEN.
"""
import asyncio
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Thêm project root vào sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company

SENTIMENT_LABEL = {"POS": "Tích cực", "NEG": "Tiêu cực", "NEU": "Trung lập"}


async def export(hours: int = 168, output_file: str | None = None) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, Company)
            .join(Company, ArticleMeta.company_id == Company.id)
            .where(ArticleMeta.published_at >= since)
            .order_by(ArticleMeta.published_at.desc())
        )
        rows = result.fetchall()

    if not output_file:
        label = f"{hours}h" if hours < 48 else f"{hours // 24}d"
        output_file = f"articles_{datetime.now().strftime('%Y%m%d_%H%M')}_{label}.csv"

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker", "company", "sentiment", "score",
            "published_at (ICT)", "title", "url",
        ])
        vn_tz = timezone(timedelta(hours=7))
        for art, company in rows:
            pub_vn = art.published_at.astimezone(vn_tz).strftime("%Y-%m-%d %H:%M")
            writer.writerow([
                company.ticker,
                company.name,
                SENTIMENT_LABEL.get(art.sentiment or "", art.sentiment or ""),
                f"{(art.sentiment_score or 0):.2f}",
                pub_vn,
                art.title,
                art.url,
            ])

    print(f"✓ Xuất {len(rows)} bài → {output_file}")
    return output_file


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 168
    out   = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(export(hours, out))
