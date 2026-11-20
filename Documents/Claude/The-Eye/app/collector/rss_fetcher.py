"""
RSS Fetcher — poll feeds, filter by company keywords, lưu article_meta.
Chạy theo interval trong scheduler.
"""
import asyncio
import html as html_lib
import logging
import re
import time
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company, FeedSource
from app.config import load_companies, load_sources

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


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern:
    """
    Regex match keyword theo ranh giới từ (word boundary, hỗ trợ tiếng Việt).
    Tránh false positive kiểu "VIC" khớp "VICEM"/"Vicostone", "NAF" khớp "NAFTA".
    """
    kw = re.escape(_normalize_text(keyword)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){kw}(?!\w)")


def _first_match_pos(text: str, keywords: list[str]) -> int | None:
    positions = [m.start() for kw in keywords if (m := _keyword_pattern(kw).search(text))]
    return min(positions) if positions else None


def _match_company(text: str, companies: list[dict], title: str | None = None) -> int | None:
    """
    Trả về company_id phù hợp nhất:
      1. Ưu tiên công ty được nhắc trong tiêu đề (nếu truyền title)
      2. Trong cùng phạm vi, chọn công ty xuất hiện sớm nhất
    """
    for scope in ([title] if title else []) + [text]:
        normalized = _normalize_text(scope)
        best: tuple[int, int] | None = None   # (position, db_id)
        for company in companies:
            pos = _first_match_pos(normalized, company["keywords"])
            if pos is not None and (best is None or pos < best[0]):
                best = (pos, company["db_id"])
        if best:
            return best[1]
    return None


# Google News gắn " - Tên báo" vào cuối tiêu đề → bỏ đi để dedup với nguồn gốc
_GOOGLE_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,60}$")


def _clean_title(title: str, is_google: bool = False) -> str:
    """Unescape HTML entities, chuẩn hoá khoảng trắng, bỏ hậu tố nguồn của Google News."""
    cleaned = re.sub(r"\s+", " ", html_lib.unescape(title or "")).strip()
    if is_google:
        stripped = _GOOGLE_SUFFIX_RE.sub("", cleaned).strip()
        if len(stripped) >= 15:   # chỉ bỏ nếu phần còn lại vẫn là tiêu đề hợp lệ
            cleaned = stripped
    return cleaned


def _clean_summary(summary: str) -> str:
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", summary or ""))
    return re.sub(r"\s+", " ", text).strip()


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
        parsed = await asyncio.to_thread(feedparser.parse, resp.content)
        return parsed.entries or []
    except Exception as e:
        log.warning(f"Feed fetch error [{url}]: {e}")
        return []


async def load_active_companies(session) -> list[dict]:
    """
    Danh sách công ty đang theo dõi LẤY TỪ DATABASE (nguồn chuẩn).
    companies.yaml chỉ dùng để thêm/cập nhật công ty (đồng bộ lúc khởi động) —
    công ty chỉ có trong DB (VD thêm từ máy khác) vẫn được theo dõi.
    """
    cfg = {c["ticker"]: c for c in load_companies()}
    result = await session.execute(select(Company).where(Company.active == True))  # noqa: E712
    out = []
    for db_obj in result.scalars().all():
        keywords = list(db_obj.keywords or []) or cfg.get(db_obj.ticker, {}).get("keywords", [])
        if not keywords:
            continue
        out.append({"ticker": db_obj.ticker, "name": db_obj.name, "keywords": keywords, "db_id": db_obj.id})
    return out


async def rematch_existing(days: int = 120) -> dict:
    """
    Sau khi đổi từ khoá: bài nào KHÔNG còn khớp công ty đang gắn thì gắn lại công ty khớp,
    hoặc bỏ gắn (company_id = NULL) nếu không khớp công ty nào. Không xoá bài.
    Bài vẫn khớp công ty hiện tại thì giữ nguyên.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    moved = unlinked = 0
    async with AsyncSessionLocal() as session:
        companies = await load_active_companies(session)
        by_id = {c["db_id"]: c for c in companies}
        rows = await session.execute(
            select(ArticleMeta).where(ArticleMeta.company_id != None)  # noqa: E711
            .where(ArticleMeta.published_at >= since)
        )
        for art in rows.scalars().all():
            current = by_id.get(art.company_id)
            if current is None:
                continue                    # công ty đã tắt theo dõi → không đụng
            text = f"{art.title} {art.summary or ''}"
            if _match_company(text, [current], title=art.title) is not None:
                continue
            new_id = _match_company(text, companies, title=art.title)
            art.company_id = new_id
            if new_id is None:
                unlinked += 1
            else:
                moved += 1
        await session.commit()
    log.info(f"rematch_existing: chuyển {moved} bài sang công ty khác, bỏ gắn {unlinked} bài")
    return {"moved": moved, "unlinked": unlinked}


FETCH_CONCURRENCY = 5
_google_last_poll: float = 0.0


def _google_due(google_cfg: dict | None) -> bool:
    """Google News có poll_interval_sec riêng (mặc định 600s) để tránh rate limit."""
    if not google_cfg or not google_cfg.get("active", True):
        return False
    interval = google_cfg.get("poll_interval_sec", 600)
    # Trừ 30s dung sai vì scheduler chạy mỗi 300s
    return time.monotonic() - _google_last_poll >= interval - 30 or _google_last_poll == 0.0


def _mark_google_polled() -> None:
    global _google_last_poll
    _google_last_poll = time.monotonic()


async def poll_feeds() -> list[int]:
    """
    Poll tất cả active feeds, lưu bài mới vào article_meta.
    Trả về list article_id mới để classifier xử lý tiếp.
    """
    sources_cfg = load_sources()
    new_article_ids: list[int] = []

    async with AsyncSessionLocal() as session:
        companies_with_id = await load_active_companies(session)

        # Lấy source_id map
        result = await session.execute(select(FeedSource).where(FeedSource.active == True))
        db_sources = {s.source_id: s.id for s in result.scalars().all()}

        fixed_feeds = [
            (f, db_sources[f["id"]])
            for f in sources_cfg
            if f.get("type") != "google_rss" and f["id"] in db_sources
        ]
        google_cfg = next((f for f in sources_cfg if f.get("type") == "google_rss"), None)
        google_source_db_id = db_sources.get("google_news_template")
        google_due = google_source_db_id is not None and _google_due(google_cfg)

        async with httpx.AsyncClient(headers=HEADERS) as client:
            sem = asyncio.Semaphore(FETCH_CONCURRENCY)

            async def fetch(url: str) -> list:
                async with sem:
                    return await _fetch_feed(url, client)

            # Feed cố định — fetch song song (giới hạn concurrency)
            fixed_results = await asyncio.gather(*(fetch(f["url"]) for f, _ in fixed_feeds))

            # Google News RSS — 1 feed/company, tuần tự + delay để tránh rate limit
            google_results: list[list] = []
            if google_due:
                for i, company in enumerate(companies_with_id):
                    if i > 0:
                        await asyncio.sleep(1)
                    google_results.append(await _fetch_feed(_build_google_rss_url(company), client))
                _mark_google_polled()

        # Lưu vào DB tuần tự (một session không dùng đồng thời được)
        batches = [
            (entries, source_id, False)
            for (_, source_id), entries in zip(fixed_feeds, fixed_results)
        ] + [(entries, google_source_db_id, True) for entries in google_results]

        for entries, source_id, is_google in batches:
            for entry in entries:
                ids = await _save_entry(
                    session, entry, source_id, companies_with_id, is_google=is_google
                )
                new_article_ids.extend(ids)

        await session.commit()

    log.info(f"poll_feeds: {len(new_article_ids)} new articles")
    return new_article_ids


async def _save_entry(
    session, entry, source_db_id: int, companies: list[dict], is_google: bool = False
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

    title_clean = _clean_title(title, is_google=is_google)
    summary_clean = _clean_summary(summary)
    # Google News summary chỉ lặp lại tiêu đề + tên báo → không có giá trị
    if is_google and title_clean.lower() in summary_clean.lower():
        summary_clean = ""

    search_text = f"{title_clean} {summary_clean}"
    company_id = _match_company(search_text, companies, title=title_clean)

    if company_id is None:
        return []

    published_at = _parse_pubdate(entry)

    # Bỏ qua bài cũ hơn 48h — tránh RSS feed trả về bài cũ gây thông báo sai
    cutoff_48h = datetime.now(timezone.utc) - timedelta(hours=48)
    if published_at < cutoff_48h:
        log.debug(f"Skipping old article (published {published_at.isoformat()}): {title[:60]}")
        return []

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
