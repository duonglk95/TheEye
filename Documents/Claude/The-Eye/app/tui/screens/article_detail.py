"""
ArticleDetailScreen — popup chi tiết bài báo khi nhấn Enter.
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.containers import Vertical, ScrollableContainer

SENTIMENT_ICON  = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
SENTIMENT_LABEL = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}
SENTIMENT_COLOR = {"POS": "green", "NEG": "red", "NEU": "dim"}


class ArticleDetailScreen(ModalScreen):

    BINDINGS = [
        Binding("escape", "dismiss", "Đóng"),
        Binding("q",      "dismiss", "Đóng"),
    ]

    def __init__(self, article: dict):
        self.article = article
        super().__init__()

    def compose(self) -> ComposeResult:
        art = self.article
        sentiment = art.get("sentiment", "NEU")
        icon  = SENTIMENT_ICON.get(sentiment, "⚪")
        label = SENTIMENT_LABEL.get(sentiment, "")
        color = SENTIMENT_COLOR.get(sentiment, "dim")
        score_pct = int((art.get("score") or 0) * 100)
        method = art.get("method", "rule")

        with Vertical(id="detail-container"):
            yield Static(
                f"  👁  CHI TIẾT BÀI BÁO   [dim][ ESC để đóng ][/dim]",
                id="detail-header",
            )
            yield Static("  " + "─" * 80, classes="sidebar-divider")

            yield Static(
                f"\n  [{color} bold]{icon}  {art['ticker']}  —  {label}  ({score_pct}%)[/{color} bold]"
                f"  [dim]via {method}[/dim]",
                id="detail-sentiment",
            )
            yield Static(
                f"  [bold white]{art['title']}[/bold white]",
                id="detail-title",
            )
            yield Static(
                f"  [dim]🕐 {art.get('published_at', '')}   📰 {art.get('source', '')}[/dim]",
                id="detail-meta",
            )
            yield Static("  " + "─" * 80, classes="sidebar-divider")

            with ScrollableContainer(id="detail-summary"):
                summary = art.get("summary") or "[dim]Chưa có tóm tắt[/dim]"
                yield Static(f"  {summary}")

            yield Static("  " + "─" * 80, classes="sidebar-divider")
            yield Static(
                f"  [link={art.get('url', '')}][dim]{art.get('url', '')}[/dim][/link]",
                id="detail-url",
            )
            yield Static(
                "\n  [dim][ ESC / Q ] Đóng[/dim]",
            )
