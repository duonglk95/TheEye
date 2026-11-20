"""
Report builder — tạo báo cáo doanh nghiệp từ DB.
Dùng chung cho bot commands và digest.
"""
import html as html_lib
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.db import AsyncSessionLocal
from app.notifier.formatting import (
    Report, article_item, counts_line, esc, footer, mood_line,
)
from app.notifier.rating import MAX_ROWS
from app.db.models import ArticleMeta, Company, FeedSource

VN_TZ = timezone(timedelta(hours=7))
SENTIMENT_ICON  = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
SENTIMENT_LABEL = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}


def _pub(published_at) -> str:
    return published_at.astimezone(VN_TZ).strftime("%H:%M %d/%m")


async def get_company(ticker: str) -> Company | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Company).where(
                func.upper(Company.ticker) == ticker.upper(),
                Company.active == True,   # noqa
            )
        )
        return result.scalar_one_or_none()


async def get_all_companies() -> list[Company]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Company).where(Company.active == True).order_by(Company.ticker)  # noqa
        )
        return list(result.scalars().all())


async def build_company_report(ticker: str, hours: int = 24) -> str:
    """
    Báo cáo đầy đủ cho 1 công ty.
    Trả về chuỗi đã format HTML cho Telegram.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with AsyncSessionLocal() as session:
        company = await session.scalar(
            select(Company).where(func.upper(Company.ticker) == ticker.upper())
        )
        if not company:
            return f"❌ Không tìm thấy ticker <b>{ticker.upper()}</b>.\nDùng /list để xem danh sách."

        # Tổng hợp theo sentiment
        count_result = await session.execute(
            select(ArticleMeta.sentiment, func.count(ArticleMeta.id).label("cnt"))
            .where(ArticleMeta.company_id == company.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.sentiment != None)   # noqa
            .group_by(ArticleMeta.sentiment)
        )
        counts = {r.sentiment: r.cnt for r in count_result.fetchall()}
        total = sum(counts.values())

        if total == 0:
            label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"
            return (
                f"📭 <b>[{company.ticker}] {company.name}</b>\n"
                f"Không có tin nào trong {label_range} qua."
            )

        # Top POS (max 3)
        pos_articles = await session.execute(
            select(ArticleMeta, FeedSource)
            .outerjoin(FeedSource, ArticleMeta.source_id == FeedSource.id)
            .where(ArticleMeta.company_id == company.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.sentiment == "POS")
            .order_by(ArticleMeta.sentiment_score.desc())
            .limit(3)
        )
        pos_rows = pos_articles.fetchall()

        # Top NEG (max 3)
        neg_articles = await session.execute(
            select(ArticleMeta, FeedSource)
            .outerjoin(FeedSource, ArticleMeta.source_id == FeedSource.id)
            .where(ArticleMeta.company_id == company.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.sentiment == "NEG")
            .order_by(ArticleMeta.sentiment_score.desc())
            .limit(3)
        )
        neg_rows = neg_articles.fetchall()

        # Top NEU (max 2)
        neu_articles = await session.execute(
            select(ArticleMeta, FeedSource)
            .outerjoin(FeedSource, ArticleMeta.source_id == FeedSource.id)
            .where(ArticleMeta.company_id == company.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.sentiment == "NEU")
            .order_by(ArticleMeta.published_at.desc())
            .limit(3)
        )
        neu_rows = neu_articles.fetchall()

    # ── Format báo cáo ──
    now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m")
    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"
    pos_c, neg_c, neu_c = counts.get("POS", 0), counts.get("NEG", 0), counts.get("NEU", 0)

    lines = [
        f"📊 <b>{esc(company.ticker)} · {esc(company.name)}</b>",
        f"<i>{label_range} qua · cập nhật {now_str}</i>",
        "",
        counts_line(pos_c, neg_c, neu_c),
        mood_line(pos_c, neg_c),
    ]

    sections = [("📈 <b>Tích cực</b>", pos_rows, pos_c),
                ("📉 <b>Tiêu cực</b>", neg_rows, neg_c),
                ("📋 <b>Trung lập</b>", neu_rows, neu_c)]
    ids: list[int] = []
    for heading, rows, total_in_group in sections:
        if not rows:
            continue
        lines += ["", heading]
        for i, (art, src) in enumerate(rows):
            if i:
                lines.append("")
            ids.append(art.id)
            lines.append(article_item(art, src, index=len(ids)))
        if total_in_group > len(rows):
            lines.append(f"<i>+ {total_in_group - len(rows)} tin khác</i>")

    lines.append(footer())
    return Report("\n".join(lines), ids)


async def build_overview_report(hours: int = 24) -> str:
    """Báo cáo tổng quan tất cả công ty đang monitor."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"

    async with AsyncSessionLocal() as session:
        companies = await session.scalars(
            select(Company).where(Company.active == True).order_by(Company.ticker)  # noqa
        )
        companies = list(companies.all())

        lines = [
            f"📋 <b>Tổng quan · {label_range} qua</b>",
            f"<i>cập nhật {now_str}</i>",
            "",
        ]

        for company in companies:
            count_result = await session.execute(
                select(ArticleMeta.sentiment, func.count(ArticleMeta.id).label("cnt"))
                .where(ArticleMeta.company_id == company.id)
                .where(ArticleMeta.published_at >= since)
                .where(ArticleMeta.sentiment != None)   # noqa
                .group_by(ArticleMeta.sentiment)
            )
            counts = {r.sentiment: r.cnt for r in count_result.fetchall()}
            total = sum(counts.values())
            pos_c, neg_c, neu_c = counts.get("POS", 0), counts.get("NEG", 0), counts.get("NEU", 0)

            if total == 0:
                lines.append(f"▫️ <b>{esc(company.ticker)}</b> {esc(company.name)}\n<i>không có tin</i>")
                continue
            trend = "📈" if pos_c > neg_c else "📉" if neg_c > pos_c else "➖"
            lines.append(
                f"{trend} <b>{esc(company.ticker)}</b> {esc(company.name)}\n"
                f"<i>🟢 {pos_c} · 🔴 {neg_c} · ⚪ {neu_c} · {total} bài</i>"
            )

    lines.append(footer("/report TICKER để xem chi tiết"))
    return "\n".join(lines)


async def search_articles(keyword: str, hours: int = 48, limit: int = 8) -> str:
    """Tìm kiếm bài báo theo từ khóa trong title hoặc summary."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"
    kw = f"%{keyword}%"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, Company)
            .join(Company, ArticleMeta.company_id == Company.id)
            .where(
                (ArticleMeta.title.ilike(kw)) | (ArticleMeta.summary.ilike(kw))
            )
            .where(ArticleMeta.published_at >= since)
            .order_by(ArticleMeta.published_at.desc())
            .limit(limit)
        )
        rows = result.fetchall()

    kw_escaped = html_lib.escape(keyword)
    if not rows:
        return (
            f"🔍 Không tìm thấy bài nào chứa «<b>{kw_escaped}</b>» "
            f"trong {label_range} qua."
        )

    lines = [
        f"🔍 <b>«{kw_escaped}»</b> · {len(rows)} bài trong {label_range} qua",
        "",
    ]
    for i, (art, company) in enumerate(rows):
        if i:
            lines.append("")
        lines.append(article_item(art, None, index=i + 1 if i < MAX_ROWS else None, ticker=company.ticker))
    lines.append(footer())
    return Report("\n".join(lines), [art.id for art, _ in rows])


async def build_top_report(sentiment: str, hours: int = 24, limit: int = 5) -> str:
    """Top POS hoặc NEG across tất cả công ty."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"
    icon = SENTIMENT_ICON.get(sentiment, "⚪")
    label = SENTIMENT_LABEL.get(sentiment, sentiment)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, Company, FeedSource)
            .join(Company, ArticleMeta.company_id == Company.id)
            .outerjoin(FeedSource, ArticleMeta.source_id == FeedSource.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.sentiment == sentiment)
            .order_by(ArticleMeta.sentiment_score.desc())
            .limit(limit)
        )
        rows = result.fetchall()

    if not rows:
        return f"{icon} Không có tin <b>{label}</b> nào trong {label_range} qua."

    lines = [
        f"{icon} <b>Top {limit} tin {label.lower()} · {label_range} qua</b>",
        f"<i>cập nhật {now_str}</i>",
    ]
    for i, (art, company, src) in enumerate(rows, 1):
        lines += ["", article_item(art, src, index=i, ticker=company.ticker)]

    lines.append(footer())
    return Report("\n".join(lines), [art.id for art, _, _ in rows])
