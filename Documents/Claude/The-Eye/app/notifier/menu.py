"""
Bàn phím nút cố định — người dùng không cần gõ lệnh.

Sau /start (hoặc /menu), bàn phím gõ chữ được thay bằng các nút luôn hiện sẵn:

  ┌──────────┬──────────┬──────────┐
  │ 📊 SBT   │ 📊 DGC   │ 📊 NAF   │   ← chạm = báo cáo 24h của công ty
  │ 📊 VIC   │ 📊 CTD   │          │
  │📋 Tổng quan│🟢 Tin tốt│🔴 Tin xấu│
  │ 🔔 Bật thông báo (chat riêng)  │
  └────────────────────────────────┘

Chạm nút = Telegram gửi đúng chữ trên nút → bot nhận diện và trả báo cáo
(kèm hàng 🔴 Xấu / ⚪ Thường / 🟢 Tốt để chấm tin).
Trong group cần tắt Privacy Mode của bot (BotFather → /setprivacy → Disable) để bot thấy nút được chạm.
"""
import logging
import re

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from app.notifier.rating import keyboard as rating_keyboard
from app.notifier.rating import to_telegram_markup

log = logging.getLogger(__name__)

BTN_ALL = "📋 Tổng quan"
BTN_POS = "🟢 Tin tốt"
BTN_NEG = "🔴 Tin xấu"
BTN_SUB = "🔔 Bật thông báo"
BTN_UNSUB = "🔕 Tắt thông báo"
TICKER_PREFIX = "📊 "

# Regex cho MessageHandler: chỉ bắt đúng chữ trên các nút
BUTTON_PATTERN = re.compile(
    rf"^({re.escape(TICKER_PREFIX)}[A-Z0-9]{{2,5}}|{BTN_ALL}|{BTN_POS}|{BTN_NEG}|{BTN_SUB}|{BTN_UNSUB})$"
)

MENU_TEXT = (
    "👋 <b>Chào bạn, mình là Bao</b>\n"
    "Chạm nút bên dưới để xem tin.\n"
    "<i>Dưới mỗi tin có 🔴 Xấu / ⚪ Thường / 🟢 Tốt: Hãy giúp Bao sẽ giỏi hơn bằng cách đánh giá tin nhé</i>"
)


async def _is_subscribed(chat_id: int) -> bool:
    from app.notifier.subscriber import get_subscriber
    sub = await get_subscriber(chat_id)
    return bool(sub and sub.active)


async def reply_keyboard(chat) -> ReplyKeyboardMarkup:
    from app.notifier.report_builder import get_all_companies

    companies = await get_all_companies()
    tickers = [KeyboardButton(f"{TICKER_PREFIX}{c.ticker}") for c in companies]
    rows = [tickers[i:i + 3] for i in range(0, len(tickers), 3)]
    rows.append([KeyboardButton(BTN_ALL), KeyboardButton(BTN_POS), KeyboardButton(BTN_NEG)])
    if chat.type == ChatType.PRIVATE:
        rows.append([KeyboardButton(BTN_UNSUB if await _is_subscribed(chat.id) else BTN_SUB)])
    return ReplyKeyboardMarkup(
        rows, resize_keyboard=True, is_persistent=True,
        input_field_placeholder="Chạm nút để xem tin…",
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/start, /menu, /help — hiện bàn phím nút. /start trong chat riêng = bật thông báo luôn."""
    chat = update.effective_chat
    note = ""
    if chat.type == ChatType.PRIVATE and (update.message.text or "").startswith("/start"):
        from app.notifier.subscriber import subscribe
        user = update.effective_user
        _, status = await subscribe(chat_id=chat.id, username=user.username, first_name=user.first_name)
        if status in ("new", "reactivated"):
            note = "\n\n🔔 Đã bật thông báo: Bao sẽ nhắn bạn khi có tin xấu quan trọng."
    await update.message.reply_text(
        MENU_TEXT + note, parse_mode=ParseMode.HTML, reply_markup=await reply_keyboard(chat),
    )


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý khi người dùng chạm 1 nút trên bàn phím cố định."""
    from app.notifier.report_builder import build_company_report, build_overview_report, build_top_report

    text = (update.message.text or "").strip()
    chat = update.effective_chat

    if text in (BTN_SUB, BTN_UNSUB):
        from app.notifier.subscriber import subscribe, unsubscribe
        if text == BTN_SUB:
            user = update.effective_user
            await subscribe(chat_id=chat.id, username=user.username, first_name=user.first_name)
            msg = "🔔 Đã bật thông báo. Bao sẽ nhắn bạn khi có tin xấu quan trọng."
        else:
            await unsubscribe(chat.id)
            msg = "🔕 Đã tắt thông báo. Bạn vẫn xem tin bằng các nút bên dưới."
        await update.message.reply_text(msg, reply_markup=await reply_keyboard(chat))
        return

    if text.startswith(TICKER_PREFIX):
        report = await build_company_report(text[len(TICKER_PREFIX):], 24)
    elif text == BTN_ALL:
        report = await build_overview_report(24)
    elif text == BTN_POS:
        report = await build_top_report("POS", 24)
    elif text == BTN_NEG:
        report = await build_top_report("NEG", 24)
    else:
        return

    await update.message.reply_text(
        report, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        reply_markup=to_telegram_markup(rating_keyboard(getattr(report, "article_ids", []))),
    )
