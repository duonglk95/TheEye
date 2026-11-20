"""
Article Scraper — fetch full content async sau khi article_meta đã lưu.
Chạy background, phục vụ Phase 2 training.
"""
import logging
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import ArticleContent, ArticleMeta

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TheEye/1.0; content scraper)"}

# CSS selectors ưu tiên theo domain
CONTENT_SELECTORS = {
    "cafef.vn":     ["div.detail-content", "div.body", "article"],
    "vietstock.vn": ["div.article-content", "div.content-detail", "article"],
    "vnexpress.net": ["article.fck_detail", "div.sidebar-1", "article"],
}


def _extract_text(html: str, url: str) -> str:
    """Extract clean text từ HTML dùng domain-specific selectors."""
    soup = BeautifulSoup(html, "lxml")

    # Xóa script/style/ads
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    domain = next(
        (d for d in CONTENT_SELECTORS if d in url), None
    )
    if domain:
        for selector in CONTENT_SELECTORS[domain]:
            el = soup.select_one(selector)
            if el:
                return re.sub(r"\n{3,}", "\n\n", el.get_text("\n")).strip()

    # Fallback: lấy <article> hoặc <main> hoặc toàn body
    for tag in ["article", "main"]:
        el = soup.find(tag)
        if el:
            return re.sub(r"\n{3,}", "\n\n", el.get_text("\n")).strip()

    return re.sub(r"\n{3,}", "\n\n", soup.body.get_text("\n")).strip() if soup.body else ""


async def scrape_article(article_id: int) -> bool:
    """
    Scrape full content cho 1 article.
    Trả về True nếu thành công.
    """
    async with AsyncSessionLocal() as session:
        article = await session.get(ArticleMeta, article_id)
        if not article:
            return False

        # Bỏ qua nếu đã scrape
        existing = await session.get(ArticleContent, article_id)
        if existing and existing.scraped_at:
            return True

        error = None
        content_raw = None
        content_html = None

        try:
            if "news.google.com" in article.url:
                # Link Google News là trang chuyển hướng bằng JS — không lấy được nội dung thật
                raise ValueError("google_news_redirect: không scrape được")
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    article.url, headers=HEADERS, timeout=20, follow_redirects=True
                )
                resp.raise_for_status()
                content_html = resp.text[:500_000]  # cap 500KB
                content_raw = _extract_text(content_html, article.url)
        except Exception as e:
            error = str(e)[:500]
            log.warning(f"Scrape failed [{article.url}]: {e}")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        if existing:
            existing.content_raw = content_raw
            existing.content_html = content_html
            existing.word_count = len(content_raw.split()) if content_raw else 0
            existing.scraped_at = now if not error else None
            existing.scrape_error = error
        else:
            session.add(ArticleContent(
                article_id=article_id,
                content_raw=content_raw,
                content_html=content_html,
                word_count=len(content_raw.split()) if content_raw else 0,
                scraped_at=now if not error else None,
                scrape_error=error,
            ))

        await session.commit()
        return error is None


async def scrape_pending(limit: int = 20):
    """Scrape batch các bài chưa có content. Gọi định kỳ."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta.id)
            .outerjoin(ArticleContent, ArticleMeta.id == ArticleContent.article_id)
            .where(ArticleContent.article_id == None)  # noqa: E711
            .where(~ArticleMeta.url.contains("news.google.com"))
            .order_by(ArticleMeta.published_at.desc())
            .limit(limit)
        )
        ids = [row[0] for row in result.fetchall()]

    success = 0
    for aid in ids:
        if await scrape_article(aid):
            success += 1
    log.info(f"scrape_pending: {success}/{len(ids)} succeeded")
