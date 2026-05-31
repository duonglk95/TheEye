"""
ArticleTable widget — bảng hiển thị bài báo chính.
Hỗ trợ filter, sort, keyboard navigation.
"""
from datetime import datetime, timedelta, timezone
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Input
from textual.containers import Vertical
from textual.reactive import reactive
import random

SENTIMENT_ICON = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}

DEMO_ARTICLES = [
    {
        "id": 1, "ticker": "VIC", "sentiment": "POS", "score": 0.89,
        "title": "Vingroup ký kết hợp tác chiến lược với tập đoàn Nhật Bản",
        "source": "CafeF", "published_at": "09:30 30/05",
    },
    {
        "id": 2, "ticker": "DGC", "sentiment": "NEG", "score": 0.81,
        "title": "Hóa chất Đức Giang bị phạt vi phạm quy định môi trường",
        "source": "Vietstock", "published_at": "08:15 30/05",
    },
    {
        "id": 3, "ticker": "SBT", "sentiment": "NEU", "score": 0.65,
        "title": "TTC AgriS thông báo tổ chức Đại hội đồng cổ đông thường niên",
        "source": "CafeF", "published_at": "07:45 30/05",
    },
    {
        "id": 4, "ticker": "VIC", "sentiment": "POS", "score": 0.77,
        "title": "Vinhomes bàn giao dự án Ocean Park 3 đúng tiến độ",
        "source": "VnExpress", "published_at": "10:00 30/05",
    },
    {
        "id": 5, "ticker": "CTD", "sentiment": "NEU", "score": 0.58,
        "title": "Coteccons công bố kết quả kinh doanh quý 1/2026",
        "source": "Vietstock", "published_at": "11:20 30/05",
    },
    {
        "id": 6, "ticker": "NAF", "sentiment": "POS", "score": 0.83,
        "title": "Nafoods Group ký hợp đồng xuất khẩu chanh leo sang EU",
        "source": "CafeF", "published_at": "14:05 30/05",
    },
    {
        "id": 7, "ticker": "DGC", "sentiment": "NEU", "score": 0.60,
        "title": "DGC họp HĐQT thông qua kế hoạch mở rộng nhà máy",
        "source": "Vietstock", "published_at": "13:00 30/05",
    },
    {
        "id": 8, "ticker": "VIC", "sentiment": "NEG", "score": 0.72,
        "title": "VinFast tiếp tục ghi nhận khoản lỗ lớn trong Q1/2026",
        "source": "CafeF", "published_at": "15:30 30/05",
    },
]


class ArticleTable(Widget):

    class RowSelected(Message):
        def __init__(self, article: dict):
            self.article = article
            super().__init__()

    _articles: list[dict] = []
    _row_map: dict[int, dict] = {}  # row_key → article

    def compose(self) -> ComposeResult:
        yield Input(placeholder="  / Tìm kiếm theo tiêu đề, ticker...", id="search-input")
        yield DataTable(id="main-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(
            "  ",       # sentinel
            "Thời gian",
            "Ticker",
            "Label",
            "%",
            "Tiêu đề bài báo",
            "Nguồn",
        )

    async def load_articles(
        self,
        company_ticker: str | None = None,
        sentiment: str | None = None,
        demo: bool = False,
        search: str = "",
    ) -> None:
        """Load bài báo từ DB hoặc demo data."""
        if demo:
            articles = list(DEMO_ARTICLES)
        else:
            articles = await self._fetch_from_db(company_ticker, sentiment)

        # Áp filter
        if company_ticker:
            articles = [a for a in articles if a["ticker"] == company_ticker]
        if sentiment:
            articles = [a for a in articles if a["sentiment"] == sentiment]
        if search:
            q = search.lower()
            articles = [a for a in articles if q in a["title"].lower() or q in a["ticker"].lower()]

        self._articles = articles
        self._redraw(articles)

    def _redraw(self, articles: list[dict]) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._row_map = {}

        for art in articles:
            icon = SENTIMENT_ICON.get(art["sentiment"], "⚪")
            score_str = f"{int(art['score'] * 100):3d}%"
            title = art["title"]
            if len(title) > 70:
                title = title[:68] + "…"

            row_key = table.add_row(
                "  ",
                art.get("published_at", ""),
                f" {art['ticker']} ",
                f" {icon} {art['sentiment']} ",
                f" {score_str} ",
                f"  {title}",
                f"  {art.get('source', '')}",
            )
            self._row_map[row_key.value] = art

    async def _fetch_from_db(
        self, company_ticker: str | None, sentiment: str | None
    ) -> list[dict]:
        try:
            from sqlalchemy import select
            from app.db import AsyncSessionLocal
            from app.db.models import ArticleMeta, Company, FeedSource

            vn_tz = timezone(timedelta(hours=7))
            since = datetime.now(timezone.utc) - timedelta(hours=24)

            async with AsyncSessionLocal() as session:
                q = (
                    select(ArticleMeta, Company, FeedSource)
                    .join(Company, ArticleMeta.company_id == Company.id)
                    .outerjoin(FeedSource, ArticleMeta.source_id == FeedSource.id)
                    .where(ArticleMeta.published_at >= since)
                    .order_by(ArticleMeta.published_at.desc())
                    .limit(200)
                )
                if company_ticker:
                    q = q.where(Company.ticker == company_ticker)
                if sentiment:
                    q = q.where(ArticleMeta.sentiment == sentiment)

                result = await session.execute(q)
                rows = result.fetchall()

            articles = []
            for meta, company, source in rows:
                pub = meta.published_at.astimezone(vn_tz).strftime("%H:%M %d/%m")
                articles.append({
                    "id": meta.id,
                    "ticker": company.ticker,
                    "sentiment": meta.sentiment or "NEU",
                    "score": meta.sentiment_score or 0.0,
                    "title": meta.title,
                    "source": source.name.split(" - ")[-1] if source else "",
                    "published_at": pub,
                    "url": meta.url,
                    "summary": meta.summary or "",
                    "method": meta.sentiment_method or "",
                })
            return articles
        except Exception:
            return []

    def get_selected_row(self) -> dict | None:
        table = self.query_one(DataTable)
        row_key = table.cursor_row
        if row_key is not None and 0 <= row_key < len(self._articles):
            return self._articles[row_key]
        return None

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self.app.call_later(self._do_search, event.value)

    async def _do_search(self, query: str) -> None:
        await self.load_articles(
            company_ticker=self.app.selected_company,
            sentiment=self.app.sentiment_filter,
            demo="--demo" in __import__("sys").argv,
            search=query,
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = self.get_selected_row()
        if row:
            self.post_message(self.RowSelected(row))
