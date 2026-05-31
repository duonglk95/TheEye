"""
The-Eye TUI — giao diện terminal chính
Phong cách: Claude Code terminal, có sidebar navigation + live feed.

Usage:
  python -m app.tui.app          (standalone, đọc từ DB)
  python -m app.tui.app --demo   (demo với dữ liệu giả, không cần DB)
"""
import sys
import asyncio
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, Label, ListView, ListItem,
    DataTable, Log, TabbedContent, TabPane, Digits, ProgressBar,
)
from textual.reactive import reactive
from textual import work
from textual.timer import Timer

from app.tui.widgets.sidebar import Sidebar
from app.tui.widgets.article_table import ArticleTable
from app.tui.widgets.stat_bar import StatBar
from app.tui.screens.article_detail import ArticleDetailScreen
from app.tui.screens.config_screen import ConfigScreen
from app.tui.screens.log_screen import LogScreen


DEMO_MODE = "--demo" in sys.argv


class TheEyeApp(App):
    """The-Eye — News monitoring terminal interface."""

    CSS_PATH = "styles/main.tcss"

    BINDINGS = [
        Binding("q",         "quit",           "Thoát",        priority=True),
        Binding("r",         "refresh",        "Refresh"),
        Binding("d",         "send_digest",    "Gửi Digest"),
        Binding("c",         "open_config",    "Config"),
        Binding("l",         "open_logs",      "Logs"),
        Binding("f",         "toggle_filter",  "Filter"),
        Binding("1",         "show_all",       "Tất cả"),
        Binding("2",         "filter_pos",     "POS"),
        Binding("3",         "filter_neg",     "NEG"),
        Binding("4",         "filter_neu",     "NEU"),
        Binding("slash",     "focus_search",   "Tìm kiếm"),
        Binding("escape",    "clear_filter",   "Xóa filter"),
        Binding("enter",     "view_detail",    "Xem chi tiết"),
    ]

    # Reactive state
    selected_company: reactive[str | None] = reactive(None)
    sentiment_filter: reactive[str | None] = reactive(None)
    last_refresh: reactive[datetime] = reactive(datetime.now(timezone.utc))
    article_count: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            yield Sidebar(id="sidebar")
            with Vertical(id="content-area"):
                yield StatBar(id="stat-bar")
                yield ArticleTable(id="article-table")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "👁  The-Eye"
        self.sub_title = "News Intelligence Monitor"
        self._refresh_timer = self.set_interval(300, self.action_refresh)  # 5 phút
        self.action_refresh()

    # ─── Actions ────────────────────────────────────────────────

    @work(exclusive=True)
    async def action_refresh(self) -> None:
        """Poll DB và cập nhật bảng bài viết."""
        table: ArticleTable = self.query_one("#article-table")
        stat: StatBar = self.query_one("#stat-bar")
        await table.load_articles(
            company_ticker=self.selected_company,
            sentiment=self.sentiment_filter,
            demo=DEMO_MODE,
        )
        await stat.refresh_stats(demo=DEMO_MODE)
        self.last_refresh = datetime.now(timezone.utc)
        self.notify("Đã cập nhật dữ liệu", severity="information", timeout=2)

    async def action_send_digest(self) -> None:
        if DEMO_MODE:
            self.notify("Demo mode — không gửi Telegram", severity="warning")
            return
        self.notify("Đang gửi digest...", severity="information")
        from app.notifier.telegram import send_digest
        ok = await send_digest()
        if ok:
            self.notify("✅ Đã gửi digest Telegram", severity="information")
        else:
            self.notify("❌ Gửi thất bại", severity="error")

    def action_open_config(self) -> None:
        self.push_screen(ConfigScreen())

    def action_open_logs(self) -> None:
        self.push_screen(LogScreen())

    def action_toggle_filter(self) -> None:
        sidebar: Sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("hidden")

    def action_show_all(self) -> None:
        self.sentiment_filter = None
        self._update_filter_label("Tất cả")
        self.action_refresh()

    def action_filter_pos(self) -> None:
        self.sentiment_filter = "POS"
        self._update_filter_label("🟢 POS")
        self.action_refresh()

    def action_filter_neg(self) -> None:
        self.sentiment_filter = "NEG"
        self._update_filter_label("🔴 NEG")
        self.action_refresh()

    def action_filter_neu(self) -> None:
        self.sentiment_filter = "NEU"
        self._update_filter_label("⚪ NEU")
        self.action_refresh()

    def action_clear_filter(self) -> None:
        self.sentiment_filter = None
        self.selected_company = None
        self.action_refresh()

    def action_view_detail(self) -> None:
        table: ArticleTable = self.query_one("#article-table")
        row = table.get_selected_row()
        if row:
            self.push_screen(ArticleDetailScreen(row))

    def action_focus_search(self) -> None:
        table: ArticleTable = self.query_one("#article-table")
        table.focus()

    def _update_filter_label(self, text: str) -> None:
        sidebar: Sidebar = self.query_one("#sidebar")
        sidebar.update_filter(text)

    # ─── Event handlers ─────────────────────────────────────────

    def on_sidebar_company_selected(self, event) -> None:
        self.selected_company = event.ticker
        self.action_refresh()

    def on_article_table_row_selected(self, event) -> None:
        self.action_view_detail()
