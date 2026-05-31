"""
LogScreen — xem logs hệ thống real-time.
"""
import logging
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static, Log
from textual.containers import Vertical


class TuiLogHandler(logging.Handler):
    """Forward Python logs vào Textual Log widget."""
    _instance = None

    def __init__(self):
        super().__init__()
        self._log_widget = None
        TuiLogHandler._instance = self

    def set_widget(self, widget: Log):
        self._log_widget = widget

    def emit(self, record: logging.LogRecord):
        if self._log_widget:
            level = record.levelname
            color = {"ERROR": "red", "WARNING": "yellow", "INFO": "green"}.get(level, "white")
            msg = self.format(record)
            try:
                self._log_widget.write_line(f"[{color}]{msg}[/{color}]")
            except Exception:
                pass


# Singleton handler
_tui_handler = TuiLogHandler()
_tui_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
)
logging.getLogger().addHandler(_tui_handler)


class LogScreen(ModalScreen):

    BINDINGS = [
        Binding("escape", "dismiss", "Đóng"),
        Binding("q",      "dismiss", "Đóng"),
        Binding("c",      "clear_logs", "Xóa logs"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="log-container"):
            yield Static(
                "  📋 SYSTEM LOGS   [dim][ ESC đóng  |  C xóa ][/dim]"
            )
            yield Static("  " + "─" * 74)
            yield Log(id="log-widget", highlight=True, markup=True)

    def on_mount(self) -> None:
        log_widget = self.query_one(Log)
        _tui_handler.set_widget(log_widget)
        log_widget.write_line("[dim]── Log stream bắt đầu ──[/dim]")

    def action_clear_logs(self) -> None:
        self.query_one(Log).clear()
