"""
Chấm tin 1 chạm — hàng nút có chữ dưới mỗi tin, cùng màu với nhãn của bot:

  [🔴 Xấu]  [⚪ Thường]  [🟢 Tốt]
     NEG        NEU         POS        (lưu rating 1 / 3 / 5)

Tin nhắn có nhiều bài (digest, /report) → mỗi bài 1 hàng, đầu hàng là số thứ tự bài.
Sau khi chạm, nút hiện số người đã chọn (VD "🟢 Tốt 2").
Thang 1–5 được giữ trong DB để sau này có thể thêm mức "rất tốt / rất xấu".
"""
import re

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import TrainingLabel

SCALE = [(1, "🔴 Xấu"), (3, "⚪ Thường"), (5, "🟢 Tốt")]
FACE = dict(SCALE)
MAX_ROWS = 8          # giữ bàn phím gọn trên điện thoại
CB_RE = re.compile(r"r:(\d+):([1-5])")


def rating_to_label(rating: int) -> str:
    return "NEG" if rating <= 2 else "NEU" if rating == 3 else "POS"


def keyboard(article_ids: list[int], counts: dict[int, dict[int, int]] | None = None) -> dict | None:
    """
    Bàn phím dạng dict (Telegram Bot API).
    1 bài  → 1 hàng 3 nút.  Nhiều bài → mỗi hàng có nút số thứ tự ở đầu.
    """
    ids = article_ids[:MAX_ROWS]
    if not ids:
        return None
    counts = counts or {}
    rows = []
    for i, aid in enumerate(ids, 1):
        c = counts.get(aid, {})
        row = [{"text": f"{face} {c[r]}" if c.get(r) else face, "callback_data": f"r:{aid}:{r}"}
               for r, face in SCALE]
        if len(ids) > 1:
            row.insert(0, {"text": f"{i}.", "callback_data": f"rn:{aid}"})
        rows.append(row)
    return {"inline_keyboard": rows}


def ids_from_markup(markup) -> list[int]:
    """Lấy lại danh sách bài (theo thứ tự) từ bàn phím đang hiển thị."""
    ids: list[int] = []
    for row in getattr(markup, "inline_keyboard", None) or []:
        for btn in row:
            m = CB_RE.fullmatch(getattr(btn, "callback_data", "") or "")
            if m and int(m.group(1)) not in ids:
                ids.append(int(m.group(1)))
    return ids


def merge_rows(top_rows: list[list[dict]], kb: dict | None) -> dict | None:
    """Ghép các hàng khác (VD hàng chọn thời gian) phía trên hàng nút chấm."""
    rows = list(top_rows) + (kb["inline_keyboard"] if kb else [])
    return {"inline_keyboard": rows} if rows else None


def non_rating_rows(markup) -> list[list[dict]]:
    """Các hàng không phải nút chấm trong bàn phím đang hiển thị (giữ lại khi cập nhật số phiếu)."""
    out = []
    for row in getattr(markup, "inline_keyboard", None) or []:
        datas = [getattr(b, "callback_data", "") or "" for b in row]
        if not any(d.startswith(("r:", "rn:")) for d in datas):
            out.append([{"text": b.text, "callback_data": b.callback_data} for b in row])
    return out


async def vote_counts(article_ids: list[int]) -> dict[int, dict[int, int]]:
    if not article_ids:
        return {}
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(TrainingLabel.article_id, TrainingLabel.rating, func.count())
            .where(TrainingLabel.article_id.in_(article_ids))
            .where(TrainingLabel.rating != None)  # noqa: E711
            .group_by(TrainingLabel.article_id, TrainingLabel.rating)
        )
    out: dict[int, dict[int, int]] = {}
    for aid, rating, n in rows.all():
        out.setdefault(aid, {})[rating] = n
    return out


def to_telegram_markup(kb: dict | None):
    """dict → InlineKeyboardMarkup (cho python-telegram-bot)."""
    if not kb:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row]
        for row in kb["inline_keyboard"]
    ])
