"""
Bàn phím nút cố định — người dùng không cần gõ lệnh.

Sau /start (hoặc /menu), bàn phím gõ chữ được thay bằng các nút luôn hiện sẵn (gọn, 2–3 hàng):

  ┌─────┬─────┬─────┬─────┬─────┬─────┐
  │ CTD │ DGC │ NAF │ NVL │ SBT │ VIC │   ← chạm = tin của công ty (mặc định 7 ngày)
  ├─────┴─────┼─────┴─────┼─────┴─────┤
  │ 📋 Tất cả │ 🟢 Tin tốt│ 🔴 Tin xấu│
  ├───────────┴───────────┴───────────┤
  │ 🔔 Nhận thông báo (chat riêng)    │
  └───────────────────────────────────┘

Dưới mỗi báo cáo có hàng chọn thời gian  [24 giờ] [✓ 7 ngày] [30 ngày]  — chạm để đổi ngay tại chỗ.
Admin (chat riêng) có thêm hàng nút 🔴/⚪/🟢 để chấm nhãn.
Trong group cần tắt Privacy Mode của bot (BotFather → /setprivacy → Disable) để bot thấy nút được chạm.
"""
import logging
import re

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from app.notifier.admin import is_admin_private_chat
from app.notifier.rating import keyboard as rating_keyboard
from app.notifier.rating import merge_rows, to_telegram_markup

log = logging.getLogger(__name__)

DEFAULT_HOURS = 168                     # 7 ngày
RANGES = [(24, "24 giờ"), (168, "7 ngày"), (720, "30 ngày")]

BTN_ALL = "📋 Tất cả"
BTN_POS = "🟢 Tin tốt"
BTN_NEG = "🔴 Tin xấu"
BTN_SUB = "🔔 Nhận thông báo"
BTN_UNSUB = "🔕 Tắt thông báo"

# Chỉ bắt đúng chữ trên các nút: mã cổ phiếu (2–5 ký tự in hoa) hoặc các nút chức năng
BUTTON_PATTERN = re.compile(
    rf"^([A-Z0-9]{{2,5}}|{BTN_ALL}|{BTN_POS}|{BTN_NEG}|{BTN_SUB}|{BTN_UNSUB})$"
)

MENU_TEXT = "👋 <b>Chào bạn, mình là Bao</b>\nChọn công ty bên dưới để xem tin."


async def _is_subscribed(chat_id: int) -> bool:
    from app.notifier.subscriber import get_subscriber
    sub = await get_subscriber(chat_id)
    return bool(sub and sub.active)


async def _tickers() -> list[str]:
    from app.notifier.report_builder import get_all_companies
    return [c.ticker for c in await get_all_companies()]


async def reply_keyboard(chat) -> ReplyKeyboardMarkup:
    tickers = await _tickers()
    per_row = 6 if len(tickers) <= 6 else 5
    rows = [[KeyboardButton(t) for t in tickers[i:i + per_row]] for i in range(0, len(tickers), per_row)]
    rows.append([KeyboardButton(BTN_ALL), KeyboardButton(BTN_POS), KeyboardButton(BTN_NEG)])
    if chat.type == ChatType.PRIVATE:
        rows.append([KeyboardButton(BTN_UNSUB if await _is_subscribed(chat.id) else BTN_SUB)])
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, is_persistent=True, input_field_placeholder="Chọn công ty…",
    )


# ─── Báo cáo + hàng chọn thời gian ───────────────────────────────

def range_row(kind: str, hours: int) -> list[dict]:
    """[24 giờ] [✓ 7 ngày] [30 ngày] — callback 'rg|<kind>|<hours>' (kind: rep|SBT, all, top|POS)."""
    return [
        {"text": f"✓ {label}" if h == hours else label, "callback_data": f"rg|{kind}|{h}"}
        for h, label in RANGES
    ]


def report_markup(kind: str | None, hours: int, report, admin: bool):
    """Bàn phím dưới báo cáo: hàng thời gian (nếu biết loại) + hàng chấm nhãn (chỉ admin)."""
    top = [range_row(kind, hours)] if kind else []
    rating = rating_keyboard(getattr(report, "article_ids", [])) if admin else None
    return to_telegram_markup(merge_rows(top, rating))


async def build_report(kind: str, hours: int, numbered: bool):
    from app.notifier.report_builder import build_company_report, build_overview_report, build_top_report
    parts = kind.split("|")
    if parts[0] == "rep" and len(parts) == 2:
        return await build_company_report(parts[1], hours, numbered=numbered)
    if parts[0] == "all":
        return await build_overview_report(hours)
    if parts[0] == "top" and len(parts) == 2 and parts[1] in ("POS", "NEG"):
        return await build_top_report(parts[1], hours, numbered=numbered)
    return None


# ─── Handlers ────────────────────────────────────────────────────

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/start, /menu, /help — hiện bàn phím nút. /start trong chat riêng = bật thông báo luôn."""
    chat = update.effective_chat
    note = ""
    if chat.type == ChatType.PRIVATE and (update.message.text or "").startswith("/start"):
        from app.notifier.subscriber import subscribe
        user = update.effective_user
        _, status = await subscribe(chat_id=chat.id, username=user.username, first_name=user.first_name)
        if status in ("new", "reactivated"):
            note = "\n\n🔔 Bao sẽ nhắn bạn ngay khi có tin xấu quan trọng."
    await update.message.reply_text(
        MENU_TEXT + note, parse_mode=ParseMode.HTML, reply_markup=await reply_keyboard(chat),
    )


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Người dùng chạm 1 nút trên bàn phím cố định."""
    text = (update.message.text or "").strip()
    chat = update.effective_chat

    if text in (BTN_SUB, BTN_UNSUB):
        from app.notifier.subscriber import subscribe, unsubscribe
        if text == BTN_SUB:
            user = update.effective_user
            await subscribe(chat_id=chat.id, username=user.username, first_name=user.first_name)
            msg = "🔔 Đã bật. Bao sẽ nhắn bạn ngay khi có tin xấu quan trọng."
        else:
            await unsubscribe(chat.id)
            msg = "🔕 Đã tắt thông báo. Bạn vẫn xem tin bằng các nút bên dưới."
        await update.message.reply_text(msg, reply_markup=await reply_keyboard(chat))
        return

    if text == BTN_ALL:
        kind = "all"
    elif text == BTN_POS:
        kind = "top|POS"
    elif text == BTN_NEG:
        kind = "top|NEG"
    elif text in await _tickers():
        kind = f"rep|{text}"
    else:
        return                      # chữ in hoa ngắn nhưng không phải mã đang theo dõi → bỏ qua

    admin = is_admin_private_chat(chat.id)
    report = await build_report(kind, DEFAULT_HOURS, numbered=admin)
    await update.message.reply_text(
        report, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        reply_markup=report_markup(kind, DEFAULT_HOURS, report, admin),
    )


async def cb_range(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Chạm [24 giờ] / [7 ngày] / [30 ngày] → sửa báo cáo ngay tại chỗ."""
    query = update.callback_query
    m = re.fullmatch(r"rg\|(rep\|[A-Z0-9]{2,5}|all|top\|(?:POS|NEG))\|(\d{1,4})", query.data or "")
    if not m:
        await query.answer()
        return
    kind, hours = m.group(1), int(m.group(2))
    if hours not in dict(RANGES):
        await query.answer()
        return
    await query.answer()
    admin = is_admin_private_chat(update.effective_chat.id)
    report = await build_report(kind, hours, numbered=admin)
    if report is None:
        return
    try:
        await query.edit_message_text(
            report, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            reply_markup=report_markup(kind, hours, report, admin),
        )
    except Exception as e:      # "message is not modified" khi chạm lại khoảng đang chọn
        log.debug(f"range edit skipped: {e}")
