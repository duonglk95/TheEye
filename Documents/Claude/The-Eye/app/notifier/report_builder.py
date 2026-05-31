"""
Report builder — tạo báo cáo doanh nghiệp từ DB.
Dùng chung cho bot commands và digest.
"""
import html as html_lib
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company, FeedSource

VN_TZ = timezone(timedelta(hours=7))
SENTIMENT_ICON  = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
SENTIMENT_LABEL = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}


def _pct(score) -> str:
    return f"{int((score or 0) * 100)}%"


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
            .limit(2)
        )
        neu_rows = neu_articles.fetchall()

    # ── Format báo cáo ──
    now_str = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"

    lines = [
        f"📊 <b>BÁO CÁO: [{company.ticker}] {company.name}</b>",
        f"<i>⏱ {label_range} qua  •  Cập nhật lúc {now_str}</i>",
        "─────────────────────────",
    ]

    # Summary bar
    pos_c = counts.get("POS", 0)
    neg_c = counts.get("NEG", 0)
    neu_c = counts.get("NEU", 0)
    lines.append(
        f"📰 Tổng: <b>{total}</b> bài  │  "
        f"🟢 <b>{pos_c}</b>  🔴 <b>{neg_c}</b>  ⚪ {neu_c}"
    )

    # Mood indicator
    if pos_c > neg_c * 2:
        mood = "🟢 <b>Xu hướng TÍCH CỰC</b>"
    elif neg_c > pos_c * 2:
        mood = "🔴 <b>Xu hướng TIÊU CỰC</b>"
    elif neg_c > 0 and pos_c > 0:
        mood = "🟡 <b>Tín hiệu HỖN HỢP</b>"
    else:
        mood = "⚪ <b>Không có tín hiệu rõ</b>"
    lines.append(mood)

    # Theo dõi id đã hiện để dedup giữa các section
    shown_ids: set[int] = set()

    def _article_line(art, src, emoji: str, show_score: bool = True) -> str:
        src_name = html_lib.escape(src.name.split(" - ")[-1] if src else "")
        raw = art.title[:80] + "…" if len(art.title) > 80 else art.title
        title = html_lib.escape(raw)
        score_part = f" [{_pct(art.sentiment_score)}]" if show_score else ""
        return (
            f"  {emoji}{score_part} "
            f"<a href='{html_lib.escape(art.url)}'>{title}</a>\n"
            f"       <i>{_pub(art.published_at)}  {src_name}</i>"
        )

    # Top POS
    if pos_rows:
        lines.append("\n📈 <b>TIN TÍCH CỰC:</b>")
        for art, src in pos_rows:
            shown_ids.add(art.id)
            lines.append(_article_line(art, src, "🟢"))

    # Top NEG
    if neg_rows:
        lines.append("\n📉 <b>TIN TIÊU CỰC:</b>")
        for art, src in neg_rows:
            shown_ids.add(art.id)
            lines.append(_article_line(art, src, "🔴"))

    # NEU — luôn hiện, bỏ qua bài đã có trong POS/NEG (dedup)
    neu_filtered = [(art, src) for art, src in neu_rows if art.id not in shown_ids]
    if neu_filtered:
        lines.append("\n📋 <b>TIN TRUNG LẬP:</b>")
        for art, src in neu_filtered:
            lines.append(_article_line(art, src, "⚪", show_score=False))

    lines.append("\n─────────────────────────")
    lines.append(f"<i>👁 The-Eye  •  /report {company.ticker} [24h|48h|7d]</i>")

    return "\n".join(lines)


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
            f"📋 <b>TỔNG QUAN — {label_range} QUA</b>",
            f"<i>⏱ Cập nhật lúc {now_str}</i>",
            "═════════════════════════",
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
            pos_c = counts.get("POS", 0)
            neg_c = counts.get("NEG", 0)
            neu_c = counts.get("NEU", 0)

            if total == 0:
                lines.append(f"  [{company.ticker}] {company.name:<16} — Không có tin")
                continue

            # Trend arrow
            if pos_c > neg_c:
                trend = "↑"
            elif neg_c > pos_c:
                trend = "↓"
            else:
                trend = "→"

            bar_parts = []
            if pos_c: bar_parts.append(f"🟢{pos_c}")
            if neg_c: bar_parts.append(f"🔴{neg_c}")
            if neu_c: bar_parts.append(f"⚪{neu_c}")

            lines.append(
                f"  {trend} <b>[{company.ticker}]</b> {company.name:<14}"
                f"  {' '.join(bar_parts)}  <i>({total} bài)</i>"
            )

    lines.append("─────────────────────────")
    lines.append("<i>Dùng /report TICKER để xem chi tiết</i>")
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
        f"🔍 <b>KẾT QUẢ: «{kw_escaped}»</b>",
        f"<i>{len(rows)} bài trong {label_range} qua</i>",
        "─────────────────────────",
    ]
    for art, company in rows:
        emoji = SENTIMENT_ICON.get(art.sentiment, "⚪")
        raw = art.title[:80] + "…" if len(art.title) > 80 else art.title
        title = html_lib.escape(raw)
        lines.append(
            f"{emoji} <b>[{company.ticker}]</b> {_pub(art.published_at)}\n"
            f"  <a href='{html_lib.escape(art.url)}'>{title}</a>"
        )

    lines.append(f"\n<i>👁 /search {html_lib.escape(keyword)} [24h|48h|7d]</i>")
    return "\n".join(lines)


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
        f"{icon} <b>TOP {limit} TIN {label} — {label_range} QUA</b>",
        f"<i>⏱ {now_str}</i>",
        "─────────────────────────",
    ]
    for i, (art, company, src) in enumerate(rows, 1):
        src_name = html_lib.escape(src.name.split(" - ")[-1] if src else "")
        raw = art.title[:80] + "…" if len(art.title) > 80 else art.title
        title = html_lib.escape(raw)
        lines.append(
            f"{i}. <b>[{company.ticker}]</b> {icon} {_pct(art.sentiment_score)}\n"
            f"   <a href='{html_lib.escape(art.url)}'>{title}</a>\n"
            f"   <i>{_pub(art.published_at)}  {src_name}</i>"
        )

    lines.append(f"\n<i>👁 The-Eye  •  /top pos | /top neg</i>")
    return "\n".join(lines)
