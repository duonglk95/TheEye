"""
StatBar widget — thanh thống kê phía trên bảng bài viết.
Hiển thị: tổng bài / POS / NEG / NEU / thời gian poll cuối.
"""
from datetime import datetime, timedelta, timezone
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Horizontal


class StatBar(Widget):

    def compose(self) -> ComposeResult:
        yield Static("", id="stat-total")
        yield Static("  │ ", classes="stat-separator")
        yield Static("", id="stat-pos")
        yield Static("  ", classes="stat-separator")
        yield Static("", id="stat-neg")
        yield Static("  ", classes="stat-separator")
        yield Static("", id="stat-neu")
        yield Static("  │ ", classes="stat-separator")
        yield Static("", id="stat-refresh")
        yield Static("  │ ", classes="stat-separator")
        yield Static("  ● LIVE", classes="live-badge", id="stat-live")

    async def refresh_stats(self, demo: bool = False) -> None:
        if demo:
            total, pos, neg, neu = 27, 8, 3, 16
        else:
            total, pos, neg, neu = await self._query_stats()

        vn_tz = timezone(timedelta(hours=7))
        now_str = datetime.now(vn_tz).strftime("%H:%M:%S")

        try:
            self.query_one("#stat-total").update(
                f"  📰 [bold]{total}[/bold] bài / 24h"
            )
            self.query_one("#stat-pos").update(
                f"🟢 [bold green]{pos}[/bold green] POS"
            )
            self.query_one("#stat-neg").update(
                f"🔴 [bold red]{neg}[/bold red] NEG"
            )
            self.query_one("#stat-neu").update(
                f"⚪ {neu} NEU"
            )
            self.query_one("#stat-refresh").update(
                f"  Cập nhật: [dim]{now_str}[/dim]"
            )
        except Exception:
            pass

    async def _query_stats(self) -> tuple[int, int, int, int]:
        try:
            from sqlalchemy import select, func
            from app.db import AsyncSessionLocal
            from app.db.models import ArticleMeta

            since = datetime.now(timezone.utc) - timedelta(hours=24)
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        ArticleMeta.sentiment,
                        func.count(ArticleMeta.id).label("cnt"),
                    )
                    .where(ArticleMeta.published_at >= since)
                    .where(ArticleMeta.sentiment != None)  # noqa
                    .group_by(ArticleMeta.sentiment)
                )
                rows = {r.sentiment: r.cnt for r in result.fetchall()}

            pos = rows.get("POS", 0)
            neg = rows.get("NEG", 0)
            neu = rows.get("NEU", 0)
            return pos + neg + neu, pos, neg, neu
        except Exception:
            return 0, 0, 0, 0
