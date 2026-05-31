"""
Telegram notifier — 2 chế độ:
  1. send_immediate(article_id)  — gửi ngay khi phát hiện POS/NEG
  2. send_digest()               — gửi tổng hợp tin mới mỗi 2 tiếng
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

SENTIMENT_EMOJI = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
SENTIMENT_LABEL = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}


async def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Gửi message Telegram, trả về True nếu thành công."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def _format_article(article: ArticleMeta, company: Company) -> str:
    emoji = SENTIMENT_EMOJI.get(article.sentiment, "⚪")
    label = SENTIMENT_LABEL.get(article.sentiment, "")
    score_pct = int((article.sentiment_score or 0) * 100)
    pub = article.published_at.astimezone(
        timezone(timedelta(hours=7))
    ).strftime("%H:%M %d/%m")

    return (
        f"{emoji} <b>[{company.ticker}] {label}</b> ({score_pct}%)\n"
        f"<b>{article.title}</b>\n"
        f"{article.summary[:200] + '...' if article.summary and len(article.summary) > 200 else article.summary or ''}\n"
        f"🕐 {pub} | <a href='{article.url}'>Đọc bài</a>"
    )


async def send_immediate(article_id: int) -> bool:
    """Gửi ngay 1 tin POS/NEG."""
    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if not article or article.notified:
            return False

        company = await session.get(Company, article.company_id)
        if not company:
            return False

        text = (
            f"⚡ <b>TIN KHẨN — THE EYE</b>\n\n"
            f"{_format_article(article, company)}"
        )

        ok = await _send(text)
        if ok:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id == article_id)
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
        return ok


async def send_digest() -> bool:
    """
    Gửi digest tổng hợp các tin mới trong 2 tiếng qua chưa được notify.
    Gộp theo company, hiển thị số lượng POS/NEG/NEU.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=2)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, Company)
            .join(Company, ArticleMeta.company_id == Company.id)
            .where(ArticleMeta.fetched_at >= since)
            .where(ArticleMeta.notified == False)  # noqa: E711
            .where(ArticleMeta.sentiment != None)  # noqa: E711
            .order_by(ArticleMeta.company_id, ArticleMeta.published_at.desc())
        )
        rows = result.fetchall()

    if not rows:
        log.info("send_digest: no new articles")
        return True

    # Gộp theo company
    by_company: dict[str, dict] = {}
    for article, company in rows:
        if company.ticker not in by_company:
            by_company[company.ticker] = {
                "company": company,
                "articles": [],
                "counts": {"POS": 0, "NEG": 0, "NEU": 0},
            }
        by_company[company.ticker]["articles"].append(article)
        by_company[company.ticker]["counts"][article.sentiment] += 1

    now_vn = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M %d/%m/%Y")
    lines = [f"📰 <b>BÁO CÁO TIN TỨC — {now_vn}</b>\n"]

    article_ids_to_mark = []

    for ticker, data in by_company.items():
        company = data["company"]
        counts = data["counts"]
        articles = data["articles"]

        # Header company
        summary_parts = []
        if counts["POS"]:
            summary_parts.append(f"🟢 {counts['POS']} tích cực")
        if counts["NEG"]:
            summary_parts.append(f"🔴 {counts['NEG']} tiêu cực")
        if counts["NEU"]:
            summary_parts.append(f"⚪ {counts['NEU']} trung lập")

        lines.append(f"<b>【{ticker}】{company.name}</b>  |  {' · '.join(summary_parts)}")

        # Top 3 bài nổi bật (POS/NEG ưu tiên trước)
        sorted_articles = sorted(
            articles,
            key=lambda a: (0 if a.sentiment in ("POS", "NEG") else 1, -(a.sentiment_score or 0))
        )
        for art in sorted_articles[:3]:
            emoji = SENTIMENT_EMOJI.get(art.sentiment, "⚪")
            score_pct = int((art.sentiment_score or 0) * 100)
            lines.append(
                f"  {emoji} <a href='{art.url}'>{art.title[:90]}</a> ({score_pct}%)"
            )

        if len(articles) > 3:
            lines.append(f"  <i>... và {len(articles) - 3} tin khác</i>")

        lines.append("")
        article_ids_to_mark.extend(a.id for a in articles)

    text = "\n".join(lines)

    # Telegram giới hạn 4096 ký tự/message
    if len(text) > 4000:
        text = text[:3980] + "\n<i>... (rút gọn)</i>"

    ok = await _send(text)
    if ok and article_ids_to_mark:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id.in_(article_ids_to_mark))
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
        log.info(f"send_digest: marked {len(article_ids_to_mark)} articles notified")

    return ok
