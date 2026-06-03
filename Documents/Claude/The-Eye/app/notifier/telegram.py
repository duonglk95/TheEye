"""
Telegram notifier:
  - send_immediate(article_id)  — gửi ngay khi phát hiện NEG
  - send_digest()               — gửi POS tổng hợp mỗi 2 tiếng
  - NEU: chỉ xem qua /report, tự động mark notified để dọn sạch queue
"""
import asyncio
import html as html_lib
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company
from app.notifier.alert_config import is_ticker_watched

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

SENTIMENT_EMOJI = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
SENTIMENT_LABEL = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}


async def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Gửi một message Telegram, trả về True nếu thành công."""
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


async def _send_chunked(text: str) -> bool:
    """
    Gửi text dài bằng cách tách thành nhiều message ≤4000 ký tự.
    Tách theo dòng để không bị cắt giữa chừng.
    """
    if len(text) <= 4000:
        return await _send(text)

    lines = text.split("\n")
    chunks, current, current_len = [], [], 0

    for line in lines:
        line_len = len(line) + 1  # +1 cho newline
        if current_len + line_len > 4000 and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    ok = True
    for chunk in chunks:
        ok = ok and await _send(chunk)
        await asyncio.sleep(0.5)  # Telegram rate limit
    return ok


def _format_article(article: ArticleMeta, company: Company) -> str:
    emoji = SENTIMENT_EMOJI.get(article.sentiment, "⚪")
    label = SENTIMENT_LABEL.get(article.sentiment, "")
    score_pct = int((article.sentiment_score or 0) * 100)
    pub = article.published_at.astimezone(
        timezone(timedelta(hours=7))
    ).strftime("%H:%M %d/%m")
    title = html_lib.escape(article.title)
    summary = article.summary or ""
    summary_text = html_lib.escape(summary[:200] + "..." if len(summary) > 200 else summary)

    return (
        f"{emoji} <b>[{company.ticker}] {label}</b> ({score_pct}%)\n"
        f"<b>{title}</b>\n"
        f"{summary_text}\n"
        f"🕐 {pub} | <a href='{html_lib.escape(article.url)}'>Đọc bài</a>"
    )


async def _send_to_chat(chat_id: int | str, text: str) -> bool:
    """Gửi message đến 1 chat_id cụ thể."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        log.error(f"Telegram send failed to {chat_id}: {e}")
        return False


async def _broadcast(text: str, ticker: str | None = None, sentiment: str | None = None) -> int:
    """
    Gửi đến:
      1. CHAT_ID chính (group/owner) — luôn nhận
      2. Tất cả subscribers active phù hợp với ticker + sentiment
    Trả về số lượng gửi thành công.
    """
    from app.notifier.subscriber import get_all_active

    targets: set[int] = {int(CHAT_ID)}  # Luôn gửi cho owner

    # Gửi cho subscribers phù hợp
    subscribers = await get_all_active()
    for sub in subscribers:
        if int(sub.chat_id) == int(CHAT_ID):
            continue  # Owner đã có trong targets

        # Kiểm tra ticker filter
        if sub.tickers and ticker and ticker.upper() not in sub.tickers:
            continue

        # Kiểm tra sentiment filter
        if sentiment and sub.sentiments and sentiment not in sub.sentiments:
            continue

        targets.add(int(sub.chat_id))

    ok_count = 0
    for chat_id in targets:
        if await _send_to_chat(chat_id, text):
            ok_count += 1
        await asyncio.sleep(0.05)  # Tránh Telegram rate limit

    return ok_count


async def send_immediate(article_id: int) -> bool:
    """
    Gửi ngay 1 tin NEG/POS tới owner + subscribers phù hợp.
    """
    cutoff_48h = datetime.now(timezone.utc) - timedelta(hours=48)

    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if not article or article.notified:
            return False

        # Bỏ qua và tự mark bài quá 48h — tránh alert tin cũ sau restart/outage
        if article.published_at < cutoff_48h:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id == article_id)
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
            log.info(
                f"[notifier] Auto-dismissed old article #{article_id} "
                f"(published_at={article.published_at.isoformat()})"
            )
            return False

        company = await session.get(Company, article.company_id)
        if not company:
            return False

        if not is_ticker_watched(company.ticker):
            log.debug(f"[notifier] Skip immediate alert for {company.ticker} — not in watchlist")
            return False

        text = (
            f"⚡ <b>HEADING NEWS — THE EYE</b>\n\n"
            f"{_format_article(article, company)}"
        )

    sent = await _broadcast(text, ticker=company.ticker, sentiment=article.sentiment)

    if sent > 0:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id == article_id)
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
        log.info(f"[notifier] Immediate alert sent to {sent} recipients for article #{article_id}")

    return sent > 0


async def send_digest() -> bool:
    """
    Digest 2 tiếng: chỉ gửi POS — NEG đã gửi ngay, NEU chỉ xem /report.
    Đồng thời mark NEU trong window là notified để dọn queue.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=2)
    cutoff_48h = datetime.now(timezone.utc) - timedelta(hours=48)

    async with AsyncSessionLocal() as session:
        # Lấy POS chưa notify — chỉ bài trong 48h theo published_at
        pos_result = await session.execute(
            select(ArticleMeta, Company)
            .join(Company, ArticleMeta.company_id == Company.id)
            .where(ArticleMeta.fetched_at >= since)
            .where(ArticleMeta.published_at >= cutoff_48h)
            .where(ArticleMeta.notified == False)   # noqa: E711
            .where(ArticleMeta.sentiment == "POS")
            .order_by(ArticleMeta.company_id, ArticleMeta.published_at.desc())
        )
        rows = pos_result.fetchall()

        # Lấy NEU để mark notified (housekeeping — không gửi)
        # Bao gồm cả bài NEU cũ hơn 48h để dọn sạch queue tồn đọng
        neu_result = await session.execute(
            select(ArticleMeta.id)
            .where(ArticleMeta.notified == False)   # noqa: E711
            .where(ArticleMeta.sentiment == "NEU")
            .where(
                (ArticleMeta.fetched_at >= since) |
                (ArticleMeta.published_at < cutoff_48h)
            )
        )
        neu_ids = [r[0] for r in neu_result.fetchall()]

    # Housekeeping NEU
    if neu_ids:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id.in_(neu_ids))
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
        log.info(f"send_digest: housekeeping {len(neu_ids)} NEU articles")

    if not rows:
        log.info("send_digest: no new POS articles")
        return True

    # Gộp theo company
    by_company: dict[str, dict] = {}
    for article, company in rows:
        if company.ticker not in by_company:
            by_company[company.ticker] = {
                "company": company,
                "articles": [],
                "count": 0,
            }
        by_company[company.ticker]["articles"].append(article)
        by_company[company.ticker]["count"] += 1

    now_vn = datetime.now(timezone(timedelta(hours=7))).strftime("%H:%M %d/%m/%Y")
    lines = [f"📈 <b>TIN TÍCH CỰC — {now_vn}</b>\n"]

    article_ids_to_mark = []

    for ticker, data in by_company.items():
        company = data["company"]
        articles = data["articles"]
        count = data["count"]

        lines.append(
            f"<b>【{ticker}】{html_lib.escape(company.name)}</b>  🟢 {count} tin"
        )

        for art in articles[:3]:
            score_pct = int((art.sentiment_score or 0) * 100)
            raw = art.title[:90] + "…" if len(art.title) > 90 else art.title
            title = html_lib.escape(raw)
            lines.append(
                f"  🟢 <a href='{html_lib.escape(art.url)}'>{title}</a> ({score_pct}%)"
            )

        if count > 3:
            lines.append(f"  <i>... và {count - 3} tin khác</i>")

        lines.append("")
        article_ids_to_mark.extend(a.id for a in articles)

    full_text = "\n".join(lines)
    ok = await _send_chunked(full_text)

    if ok and article_ids_to_mark:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(ArticleMeta)
                .where(ArticleMeta.id.in_(article_ids_to_mark))
                .values(notified=True, notified_at=datetime.now(timezone.utc))
            )
            await session.commit()
        log.info(f"send_digest: marked {len(article_ids_to_mark)} POS articles notified")

    return ok
