"""
Định dạng tin nhắn Telegram dùng chung — tối ưu cho màn hình điện thoại.

Nguyên tắc:
  - Không dùng đường kẻ dài (──── bị gãy dòng trên điện thoại) → dùng dòng trống để tách khối
  - Mỗi bài 2 dòng: dòng 1 = icon + tiêu đề (link), dòng 2 = thông tin phụ in nghiêng
  - Không thụt lề bằng dấu cách (Telegram hiển thị lệch)
  - Chân trang 1 dòng ngắn
"""
import html as html_lib
import re
from datetime import timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
ICON = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
NAME = {"POS": "Tích cực", "NEG": "Tiêu cực", "NEU": "Trung lập"}
FOOTER_BRAND = "by dlk"

# " - CafeF", " - CÔNG TY CỔ PHẦN ..." do Google News gắn vào cuối tiêu đề
_SOURCE_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,80}$")


def esc(text) -> str:
    return html_lib.escape(str(text or ""))


def confidence_text(score: float | None, method: str | None) -> str:
    """
    Độ tin cậy kèm nguồn gốc của con số:
      ml_*  → "82%"      đã hiệu chỉnh: bot nói 80% ≈ đúng 80% trên dữ liệu kiểm định
      human → "✔ đã xác nhận"
      khác  → "~50%"     ước lượng theo luật, chưa hiệu chỉnh
    """
    method = method or ""
    if method == "human":
        return "✔ đã xác nhận"
    # Không bao giờ hiển thị 100%: dữ liệu kiểm định hữu hạn không chứng minh được "chắc chắn tuyệt đối"
    pct = min(int(round((score or 0) * 100)), 99)
    return f"{pct}%" if method.startswith("ml_") else f"~{pct}%"


def feedback_keyboard(article_id: int) -> dict:
    """Nút để người đọc dạy bot: xác nhận đúng hoặc sửa nhãn."""
    return {"inline_keyboard": [[
        {"text": "✅ Đúng", "callback_data": f"fb:{article_id}:OK"},
        {"text": "🟢", "callback_data": f"fb:{article_id}:POS"},
        {"text": "🔴", "callback_data": f"fb:{article_id}:NEG"},
        {"text": "⚪", "callback_data": f"fb:{article_id}:NEU"},
    ]]}


def short_title(title: str, limit: int = 85, strip_source: bool = False) -> str:
    """Gọn tiêu đề: bỏ hậu tố tên báo (Google News), cắt ở ranh giới từ."""
    t = re.sub(r"\s+", " ", title or "").strip()
    if strip_source:
        stripped = _SOURCE_SUFFIX.sub("", t).strip()
        if len(stripped) >= 15:
            t = stripped
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-–") + "…"
    return t


def source_name(src) -> str:
    """'Vietstock - Cổ phiếu' → 'Vietstock'; 'Google News - …' → 'Google News'."""
    if not src or not getattr(src, "name", None):
        return ""
    return src.name.split(" - ")[0].strip()


def when(dt) -> str:
    return dt.astimezone(VN_TZ).strftime("%d/%m %H:%M") if dt else ""


def article_item(art, src=None, show_conf: bool = True, ticker: str | None = None) -> str:
    """
    🟢 Tiêu đề bài (link)
    SBT · 19/11 20:30 · CafeF · 82% · /why_123
    """
    is_google = "google" in (getattr(src, "name", "") or "").lower() or "news.google.com" in (art.url or "")
    title = esc(short_title(art.title, strip_source=is_google))
    meta = [x for x in (
        ticker,
        when(art.published_at),
        source_name(src),
        confidence_text(art.sentiment_score, art.sentiment_method) if show_conf else None,
        f"/why_{art.id}",
    ) if x]
    return (
        f"{ICON.get(art.sentiment, '⚪')} <a href='{esc(art.url)}'>{title}</a>\n"
        f"<i>{esc(' · '.join(meta))}</i>"
    )


def counts_line(pos: int, neg: int, neu: int) -> str:
    total = pos + neg + neu
    return f"🟢 <b>{pos}</b>   🔴 <b>{neg}</b>   ⚪ {neu}   ·   {total} bài"


def mood_line(pos: int, neg: int) -> str:
    if pos == 0 and neg == 0:
        return "Chưa có tín hiệu tốt/xấu rõ ràng"
    if pos > neg * 2:
        return "Xu hướng <b>tích cực</b> 📈"
    if neg > pos * 2:
        return "Xu hướng <b>tiêu cực</b> 📉"
    return "Tín hiệu <b>trái chiều</b> ⚖️"


def footer(*_hints: str) -> str:
    """Chân trang tối giản: chỉ ghi tác giả."""
    return f"\n<i>{FOOTER_BRAND}</i>"
