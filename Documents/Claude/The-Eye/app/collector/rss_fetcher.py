"""
RSS Fetcher — poll feeds, filter by company keywords, lưu article_meta.
Chạy theo interval trong scheduler.
"""
import asyncio
import html as html_lib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company, FeedSource
from app.config import load_sources, load_companies

log = logging.getLogger(__name__)

# User-agent để tránh bị block
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TheEye/1.0; RSS reader)"}


def _parse_pubdate(entry) -> datetime:
    """Parse published date từ feed entry, fallback về now."""
    for field in ("published", "updated"):
        val = getattr(entry, field, None)
        if val:
            try:
                return parsedate_to_datetime(val).astimezone(timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _match_company(text: str, companies: list[dict]) -> int | None:
    """Trả về company_id đầu tiên match keyword trong text."""
    normalized = _normalize_text(text)
    for company in companies:
        for kw in company["keywords"]:
            if _normalize_text(kw) in normalized:
                return company["db_id"]
    return None


def _build_google_rss_url(company: dict) -> str:
    """Tạo Google News RSS URL cho từng company."""
    query = " OR ".join(f'"{kw}"' for kw in company["keywords"][:3])
    params = {"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"}
    return f"https://news.google.com/rss/search?{urlencode(params)}"


async def _fetch_feed(url: str, client: httpx.AsyncClient) -> list:
    """Fetch và parse một RSS feed, trả về list entries."""
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)
        return parsed.entries or []
    except Exception as e:
        log.warning(f"Feed fetch error [{url}]: {e}")
        return []


async def poll_feeds() -> list[int]:
    """
    Poll tất cả active feeds, lưu bài mới vào article_meta.
    Trả về list article_id mới để classifier xử lý tiếp.
    """
    sources_cfg = load_sources()
    companies_cfg = load_companies()

    new_article_ids: list[int] = []

    async with AsyncSessionLocal() as session:
        # Lấy company db_id để match
        result = await session.execute(select(Company).where(Company.active == True))
        db_companies = result.scalars().all()
        companies_with_id = [
            {**c, "db_id": db_obj.id}
            for c in companies_cfg
            for db_obj in db_companies
            if db_obj.ticker == c["ticker"]
        ]

        # Lấy source_id map
        result = await session.execute(select(FeedSource).where(FeedSource.active == True))
        db_sources = {s.source_id: s.id for s in result.scalars().all()}

        async with httpx.AsyncClient() as client:
            # Feed cố định
            for feed_cfg in sources_cfg:
                if feed_cfg.get("type") == "google_rss":
                    continue
                source_db_id = db_sources.get(feed_cfg["id"])
                if not source_db_id:
                    continue

                entries = await _fetch_feed(feed_cfg["url"], client)
                for entry in entries:
                    ids = await _save_entry(
                        session, entry, source_db_id, companies_with_id
                    )
                    new_article_ids.extend(ids)

            # Google News RSS — 1 feed per company, delay 1s để tránh rate limit
            google_source_db_id = db_sources.get("google_news_template")
            for i, company in enumerate(companies_with_id):
                if i > 0:
                    await asyncio.sleep(1)
                url = _build_google_rss_url(company)
                entries = await _fetch_feed(url, client)
                for entry in entries:
                    ids = await _save_entry(
                        session, entry, google_source_db_id, companies_with_id
                    )
                    new_article_ids.extend(ids)

        await session.commit()

    log.info(f"poll_feeds: {len(new_article_ids)} new articles")
    return new_article_ids


async def _save_entry(
    session, entry, source_db_id: int, companies: list[dict]
) -> list[int]:
    """
    Filter và lưu một feed entry nếu liên quan đến company.
    Trả về [article_id] nếu insert thành công, [] nếu duplicate/không match.
    """
    url = getattr(entry, "link", None)
    title = getattr(entry, "title", "")
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")

    if not url or not title:
        return []

    # Strip HTML khỏi summary
    summary_clean = re.sub(r"<[^>]+>", "", summary).strip()
    search_text = f"{title} {summary_clean}"
    company_id = _match_company(search_text, companies)

    if company_id is None:
        return []

    published_at = _parse_pubdate(entry)

    # Unescape HTML entities (e.g. &nbsp; → space) rồi normalize whitespace
    title_clean = re.sub(r"\s+", " ", html_lib.unescape(title)).strip()

    # Dedup theo title trong 24h — bắt cùng bài xuất hiện ở nhiều nguồn (Google News + CafeF...)
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    title_exists = await session.scalar(
        select(ArticleMeta.id)
        .where(ArticleMeta.title == title_clean)
        .where(ArticleMeta.fetched_at >= since_24h)
        .limit(1)
    )
    if title_exists:
        return []

    stmt = (
        pg_insert(ArticleMeta)
        .values(
            url=url,
            title=title_clean,
            summary=summary_clean[:2000] if summary_clean else None,
            source_id=source_db_id,
            company_id=company_id,
            published_at=published_at,
        )
        .on_conflict_do_nothing(index_elements=["url"])
        .returning(ArticleMeta.id)
    )

    result = await session.execute(stmt)
    row = result.fetchone()
    return [row[0]] if row else []
