"""
Sidebar widget — mục lục navigation:
  ● Danh sách công ty (có badge đếm tin)
  ● Filter sentiment
  ● Trạng thái hệ thống
"""
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static, Label
from textual.containers import Vertical

COMPANIES_DEMO = [
    {"ticker": "SBT",  "name": "TTC AgriS",    "count": 3,  "neg": 0},
    {"ticker": "DGC",  "name": "Đức Giang",     "count": 7,  "neg": 1},
    {"ticker": "NAF",  "name": "Nafoods",        "count": 2,  "neg": 0},
    {"ticker": "VIC",  "name": "Vingroup",       "count": 11, "neg": 2},
    {"ticker": "CTD",  "name": "Coteccons",      "count": 4,  "neg": 0},
]


class Sidebar(Widget):

    class CompanySelected(Message):
        def __init__(self, ticker: str | None):
            self.ticker = ticker
            super().__init__()

    selected_ticker: reactive[str | None] = reactive(None)
    active_filter: reactive[str] = reactive("ALL")

    def compose(self) -> ComposeResult:
        yield Static("  ╔══════════════════╗\n"
                     "  ║   👁  THE EYE    ║\n"
                     "  ╚══════════════════╝", id="logo")
        yield Static("")
        yield Static("  CÔNG TY", classes="sidebar-section-title")
        yield Static("  ─────────────────", classes="sidebar-divider")
        yield Static(
            "  [●] Tất cả",
            id="company-all",
            classes="company-item selected",
        )
        for co in COMPANIES_DEMO:
            badge = f"🔴{co['neg']}" if co["neg"] else f"{co['count']}"
            yield Static(
                f"  [{co['ticker']}] {co['name']:<12} {badge}",
                id=f"company-{co['ticker']}",
                classes="company-item",
            )

        yield Static("")
        yield Static("  FILTER", classes="sidebar-section-title")
        yield Static("  ─────────────────", classes="sidebar-divider")
        yield Static("  [1] Tất cả",            id="f-all", classes="sentiment-filter-item filter-all active")
        yield Static("  [2] 🟢 Tích cực (POS)", id="f-pos", classes="sentiment-filter-item filter-pos")
        yield Static("  [3] 🔴 Tiêu cực (NEG)", id="f-neg", classes="sentiment-filter-item filter-neg")
        yield Static("  [4] ⚪ Trung lập (NEU)", id="f-neu", classes="sentiment-filter-item filter-neu")

        yield Static("")
        yield Static("  HỆ THỐNG", classes="sidebar-section-title")
        yield Static("  ─────────────────", classes="sidebar-divider")
        yield Static("  ● RSS  5m", id="status-rss",    classes="company-item")
        yield Static("  ● DB   OK", id="status-db",     classes="company-item")
        yield Static("  ● TG   OK", id="status-tg",     classes="company-item")

        yield Static("")
        yield Static("  PHÍM TẮT", classes="sidebar-section-title")
        yield Static("  ─────────────────", classes="sidebar-divider")
        yield Static("  [R]  Refresh",     classes="company-item")
        yield Static("  [D]  Gửi digest",  classes="company-item")
        yield Static("  [C]  Config",      classes="company-item")
        yield Static("  [L]  Logs",        classes="company-item")
        yield Static("  [/]  Tìm kiếm",   classes="company-item")
        yield Static("  [Q]  Thoát",       classes="company-item")

    def on_click(self, event) -> None:
        """Handle click trên company item."""
        node = self.get_widget_at(*event.screen_offset)
        if node and hasattr(node, "id"):
            widget_id = node.id or ""
            if widget_id == "company-all":
                self._select_company(None)
            elif widget_id.startswith("company-"):
                ticker = widget_id.replace("company-", "")
                self._select_company(ticker)

    def _select_company(self, ticker: str | None) -> None:
        # Xóa selected cũ
        for item in self.query(".company-item.selected"):
            item.remove_class("selected")

        # Highlight mới
        target_id = "company-all" if ticker is None else f"company-{ticker}"
        try:
            self.query_one(f"#{target_id}").add_class("selected")
        except Exception:
            pass

        self.selected_ticker = ticker
        self.post_message(self.CompanySelected(ticker))

    def update_filter(self, label: str) -> None:
        """Cập nhật highlight filter từ keyboard shortcut."""
        for fid in ["f-all", "f-pos", "f-neg", "f-neu"]:
            try:
                self.query_one(f"#{fid}").remove_class("active")
            except Exception:
                pass

        mapping = {"Tất cả": "f-all", "🟢 POS": "f-pos", "🔴 NEG": "f-neg", "⚪ NEU": "f-neu"}
        target = mapping.get(label, "f-all")
        try:
            self.query_one(f"#{target}").add_class("active")
        except Exception:
            pass

    def update_companies(self, companies: list[dict]) -> None:
        """Cập nhật badge đếm tin theo dữ liệu thật."""
        for co in companies:
            try:
                badge = f"🔴{co['neg']}" if co.get("neg") else str(co.get("count", 0))
                self.query_one(f"#company-{co['ticker']}").update(
                    f"  [{co['ticker']}] {co['name']:<12} {badge}"
                )
            except Exception:
                pass

    def update_system_status(self, rss: str, db: str, tg: str) -> None:
        try:
            self.query_one("#status-rss").update(f"  ● RSS  {rss}")
            self.query_one("#status-db").update(f"  ● DB   {db}")
            self.query_one("#status-tg").update(f"  ● TG   {tg}")
        except Exception:
            pass
