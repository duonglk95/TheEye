"""
Alert watchlist — quản lý danh sách ticker nhận Heading News tức thì.

Lưu trữ tại data/alert_watchlist.json:
  {"tickers": null}         → gửi cho TẤT CẢ ticker (mặc định)
  {"tickers": ["VIC","NAF"]} → chỉ gửi cho VIC và NAF

API:
  is_ticker_watched(ticker) → bool
  get_watchlist()           → list[str] | None   (None = tất cả)
  set_watchlist(tickers)    → None
  add_ticker(ticker)        → None
  remove_ticker(ticker)     → bool
  reset_to_all()            → None
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "alert_watchlist.json"


def _load() -> dict:
    if not _DATA_FILE.exists():
        return {"tickers": None}
    try:
        return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tickers": None}


def _save(data: dict) -> None:
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_watchlist() -> list[str] | None:
    """None = tất cả ticker; list = danh sách cụ thể."""
    return _load().get("tickers")


def is_ticker_watched(ticker: str) -> bool:
    watchlist = get_watchlist()
    if watchlist is None:
        return True
    return ticker.upper() in [t.upper() for t in watchlist]


def add_ticker(ticker: str) -> None:
    data = _load()
    tickers = data.get("tickers")
    if tickers is None:
        tickers = []
    upper = ticker.upper()
    if upper not in [t.upper() for t in tickers]:
        tickers.append(upper)
    data["tickers"] = tickers
    _save(data)
    log.info(f"[alert_config] Added {upper} to watchlist")


def remove_ticker(ticker: str) -> bool:
    data = _load()
    tickers = data.get("tickers")
    if tickers is None:
        return False
    upper = ticker.upper()
    new_list = [t for t in tickers if t.upper() != upper]
    if len(new_list) == len(tickers):
        return False
    data["tickers"] = new_list
    _save(data)
    log.info(f"[alert_config] Removed {upper} from watchlist")
    return True


def reset_to_all() -> None:
    _save({"tickers": None})
    log.info("[alert_config] Reset watchlist → all tickers")
