"""
Telegram Bot Handler — nhận lệnh từ group/private chat.

Danh sách lệnh:
  /report <TICKER> [24h|48h|7d]  — Báo cáo chi tiết 1 công ty
  /all [24h|48h|7d]              — Tổng quan tất cả công ty
  /top pos|neg [24h|48h|7d]      — Top tin tích cực / tiêu cực
  /list                          — Danh sách công ty đang monitor
  /status                        — Trạng thái hệ thống
  /help                          — Hướng dẫn sử dụng

Setup group:
  1. Thêm bot vào group
  2. Cấp quyền "Send Messages"
  3. Bật "Group Privacy" = OFF trong BotFather
     (hoặc dùng /command@YourBotName trong group)
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from app.notifier.report_builder import (
    build_company_report,
    build_overview_report,
    build_top_report,
    get_all_companies,
)

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Ticker aliases nhanh
TICKER_ALIASES = {
    "ttc": "SBT", "ttcagris": "SBT", "đườngbiênhòa": "SBT",
    "ducgiang": "DGC", "hóachất": "DGC",
    "nafoods": "NAF",
    "vingroup": "VIC", "vinhomes": "VIC", "vinfast": "VIC",
    "coteccons": "CTD", "cotec": "CTD",
}


def _parse_hours(arg: str | None) -> int:
    """Parse '24h', '48h', '7d' → số giờ."""
    if not arg:
        return 24
    arg = arg.lower().strip()
    if arg.endswith("d"):
        return int(arg[:-1]) * 24
    if arg.endswith("h"):
        return int(arg[:-1])
    try:
        return int(arg)
    except ValueError:
        return 24


def _normalize_ticker(raw: str) -> str:
    cleaned = raw.upper().strip()
    alias = TICKER_ALIASES.get(raw.lower().strip())
    return alias or cleaned


# ─── Command handlers ────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Gửi danh sách lệnh."""
    text = (
        "👁 <b>The-Eye — Trợ lý theo dõi tin doanh nghiệp</b>\n\n"
        "<b>Lệnh:</b>\n"
        "  /report <code>TICKER</code> <i>[24h|48h|7d]</i>\n"
        "    → Báo cáo chi tiết 1 công ty\n\n"
        "  /all <i>[24h|48h|7d]</i>\n"
        "    → Tổng quan tất cả công ty\n\n"
        "  /top <code>pos</code>|<code>neg</code> <i>[24h|48h|7d]</i>\n"
        "    → Top tin tích cực / tiêu cực\n\n"
        "  /list\n"
        "    → Danh sách ticker đang theo dõi\n\n"
        "  /status\n"
        "    → Trạng thái hệ thống\n\n"
        "<b>Ví dụ:</b>\n"
        "  <code>/report VIC</code>\n"
        "  <code>/report SBT 48h</code>\n"
        "  <code>/top neg 7d</code>\n"
        "  <code>/all</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/report TICKER [hours]"""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "⚠️ Thiếu ticker. Ví dụ: <code>/report VIC</code> hoặc <code>/report SBT 48h</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    ticker = _normalize_ticker(args[0])
    hours  = _parse_hours(args[1] if len(args) > 1 else None)

    # Gửi "đang xử lý..." trước
    wait_msg = await update.message.reply_text(
        f"⏳ Đang tổng hợp báo cáo <b>[{ticker}]</b>...",
        parse_mode=ParseMode.HTML,
    )

    report = await build_company_report(ticker, hours)
    await wait_msg.delete()
    await update.message.reply_text(
        report,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    log.info(f"[bot] /report {ticker} {hours}h → sent to chat {update.effective_chat.id}")


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/all [hours]"""
    hours = _parse_hours(ctx.args[0] if ctx.args else None)
    wait_msg = await update.message.reply_text(
        "⏳ Đang tổng hợp tổng quan...",
        parse_mode=ParseMode.HTML,
    )
    report = await build_overview_report(hours)
    await wait_msg.delete()
    await update.message.reply_text(
        report,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/top pos|neg [hours]"""
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "⚠️ Ví dụ: <code>/top pos</code> hoặc <code>/top neg 7d</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    sentiment_raw = args[0].upper()
    if sentiment_raw not in ("POS", "NEG", "NEU"):
        await update.message.reply_text(
            "⚠️ Chỉ hỗ trợ: <code>pos</code> | <code>neg</code> | <code>neu</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    hours = _parse_hours(args[1] if len(args) > 1 else None)
    wait_msg = await update.message.reply_text("⏳ Đang tìm kiếm...", parse_mode=ParseMode.HTML)
    report = await build_top_report(sentiment_raw, hours)
    await wait_msg.delete()
    await update.message.reply_text(
        report,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/list — danh sách ticker đang theo dõi."""
    companies = await get_all_companies()
    lines = ["📋 <b>DANH SÁCH CÔNG TY ĐANG THEO DÕI</b>\n"]
    for co in companies:
        lines.append(
            f"  • <b>{co.ticker}</b> — {co.name}\n"
            f"    <i>{co.sector or ''} | {co.exchange or ''}</i>"
        )
    lines.append("\n<i>Dùng /report TICKER để xem chi tiết</i>")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — trạng thái hệ thống."""
    from sqlalchemy import select, func
    from app.db import AsyncSessionLocal
    from app.db.models import ArticleMeta

    now_vn = datetime.now(timezone(timedelta(hours=7)))
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    ArticleMeta.sentiment,
                    func.count(ArticleMeta.id).label("cnt"),
                )
                .where(ArticleMeta.published_at >= since_24h)
                .group_by(ArticleMeta.sentiment)
            )
            counts = {r.sentiment: r.cnt for r in result.fetchall()}

            latest = await session.scalar(
                select(ArticleMeta.fetched_at)
                .order_by(ArticleMeta.fetched_at.desc())
                .limit(1)
            )

        total = sum(v for v in counts.values() if v)
        pos = counts.get("POS", 0)
        neg = counts.get("NEG", 0)
        neu = counts.get("NEU", 0)

        last_fetch = (
            latest.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M:%S %d/%m")
            if latest else "—"
        )
        db_status = "✅ Online"
    except Exception as e:
        total = pos = neg = neu = 0
        last_fetch = "—"
        db_status = f"❌ {str(e)[:50]}"

    text = (
        f"⚙️ <b>TRẠNG THÁI HỆ THỐNG</b>\n"
        f"<i>{now_vn.strftime('%H:%M:%S %d/%m/%Y')}</i>\n\n"
        f"  🗄 Database  : {db_status}\n"
        f"  📡 RSS Poll  : ✅ mỗi 5 phút\n"
        f"  🔔 Digest    : ✅ mỗi 2 tiếng\n"
        f"  🤖 Bot       : ✅ Online\n\n"
        f"  📊 24h qua:\n"
        f"    Tổng bài  : <b>{total}</b>\n"
        f"    🟢 POS    : <b>{pos}</b>\n"
        f"    🔴 NEG    : <b>{neg}</b>\n"
        f"    ⚪ NEU    : {neu}\n\n"
        f"  🕐 Poll cuối : {last_fetch}\n\n"
        f"<i>👁 The-Eye — News Intelligence</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý lệnh không biết."""
    await update.message.reply_text(
        "❓ Lệnh không hợp lệ. Dùng /help để xem danh sách lệnh.",
        parse_mode=ParseMode.HTML,
    )


# ─── Bot application setup ──────────────────────────────────────

def build_application() -> Application:
    """Tạo Telegram Application với đầy đủ handlers."""
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_help))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("all",    cmd_all))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CommandHandler("list",   cmd_list))

    return app


async def set_bot_commands(application: Application) -> None:
    """Đăng ký danh sách lệnh hiện trên Telegram UI."""
    commands = [
        BotCommand("report", "Báo cáo công ty: /report VIC [24h|48h|7d]"),
        BotCommand("all",    "Tổng quan tất cả: /all [24h|48h|7d]"),
        BotCommand("top",    "Top tin POS/NEG: /top pos|neg [7d]"),
        BotCommand("list",   "Danh sách công ty đang theo dõi"),
        BotCommand("status", "Trạng thái hệ thống"),
        BotCommand("help",   "Hướng dẫn sử dụng"),
    ]
    await application.bot.set_my_commands(commands)
    log.info("[bot] Commands registered on Telegram")


async def start_polling(application: Application) -> None:
    """Khởi động bot polling — gọi từ scheduler.py."""
    await application.initialize()
    await set_bot_commands(application)
    await application.start()
    await application.updater.start_polling(
        allowed_updates=["message"],
        drop_pending_updates=True,       # bỏ qua tin nhắn cũ khi restart
    )
    log.info("[bot] Polling started")


async def stop_polling(application: Application) -> None:
    """Dừng bot gracefully."""
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    log.info("[bot] Stopped")
