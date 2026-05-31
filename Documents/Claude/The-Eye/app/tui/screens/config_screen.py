"""
ConfigScreen — xem config hiện tại (companies, sources, sentiment model).
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.containers import Vertical, ScrollableContainer
from pathlib import Path
import yaml


class ConfigScreen(ModalScreen):

    BINDINGS = [
        Binding("escape", "dismiss", "Đóng"),
        Binding("q",      "dismiss", "Đóng"),
    ]

    def compose(self) -> ComposeResult:
        config_dir = Path(__file__).parent.parent.parent.parent / "config"

        with Vertical(id="config-container"):
            yield Static(
                "  ⚙️  CONFIG HIỆN TẠI   [dim][ ESC để đóng ][/dim]",
            )
            yield Static("  " + "─" * 74)

            with ScrollableContainer():
                # Companies
                yield Static("\n  [bold #7c83fd]CÔNG TY ĐANG MONITOR[/bold #7c83fd]")
                try:
                    data = yaml.safe_load((config_dir / "companies.yaml").read_text())
                    for co in data.get("companies", []):
                        active = "✅" if co.get("active") else "❌"
                        kw = ", ".join(co.get("keywords", [])[:3])
                        yield Static(
                            f"  {active}  [{co['ticker']}] [bold]{co['name']}[/bold]  "
                            f"[dim]| {co.get('sector', '')}[/dim]"
                        )
                        yield Static(f"      [dim]keywords: {kw}[/dim]")
                except Exception as e:
                    yield Static(f"  [red]Lỗi đọc companies.yaml: {e}[/red]")

                # Sentiment model
                yield Static("\n  [bold #7c83fd]SENTIMENT CONFIG[/bold #7c83fd]")
                try:
                    cfg = yaml.safe_load((config_dir / "sentiment.yaml").read_text())
                    version = cfg.get("version", "?")
                    model_path = cfg.get("model_path")
                    threshold = cfg.get("phobert_confidence_threshold", 0.75)

                    yield Static(f"  Version      : [bold #4ecca3]{version}[/bold #4ecca3]")
                    if model_path:
                        yield Static(f"  PhoBERT model: [bold #4ecca3]{model_path}[/bold #4ecca3]")
                    else:
                        yield Static("  PhoBERT model: [bold #ff6b6b]null (dùng rule-based)[/bold #ff6b6b]")
                    yield Static(f"  Threshold    : [dim]{threshold}[/dim]")

                    pos_kw = cfg.get("positive", {}).get("strong", [])
                    neg_kw = cfg.get("negative", {}).get("strong", [])
                    yield Static(f"\n  POS keywords ({len(pos_kw)}): [dim]{', '.join(pos_kw[:4])}...[/dim]")
                    yield Static(f"  NEG keywords ({len(neg_kw)}): [dim]{', '.join(neg_kw[:4])}...[/dim]")
                except Exception as e:
                    yield Static(f"  [red]Lỗi đọc sentiment.yaml: {e}[/red]")

                # Feed sources
                yield Static("\n  [bold #7c83fd]RSS FEEDS ĐANG ACTIVE[/bold #7c83fd]")
                try:
                    data = yaml.safe_load((config_dir / "sources.yaml").read_text())
                    active = [f for f in data.get("feeds", []) if f.get("active")]
                    for f in active:
                        priority_color = {
                            "high": "#4ecca3", "medium": "#7c83fd", "low": "#555577"
                        }.get(f.get("priority", "low"), "#555577")
                        yield Static(
                            f"  [{priority_color}]{f.get('priority', '').upper():6}[/{priority_color}]  "
                            f"{f['name']}"
                        )
                except Exception as e:
                    yield Static(f"  [red]Lỗi đọc sources.yaml: {e}[/red]")

                yield Static("\n  [dim]Sửa config: config/companies.yaml  |  config/sentiment.yaml[/dim]")
                yield Static("  [dim][ ESC / Q ] Đóng[/dim]\n")
