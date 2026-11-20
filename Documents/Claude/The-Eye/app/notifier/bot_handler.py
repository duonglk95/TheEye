"""
Telegram Bot Handler — nhận lệnh từ group/private chat.

Danh sách lệnh:
  /report <TICKER> [24h|48h|7d]  — Báo cáo chi tiết 1 công ty
  /all [24h|48h|7d]              — Tổng quan tất cả công ty
  /top pos|neg [24h|48h|7d]      — Top tin tích cực / tiêu cực
  /list                          — Danh sách công ty đang monitor
  /status                        — Trạng thái hệ thống
  /help                          — Hướng dẫn sử dụng
  /clear [N]                     — Xóa N tin nhắn gần đây (mặc định 50)

Setup group:
  1. Thêm bot vào group
  2. Cấp quyền "Send Messages"
  3. Bật "Group Privacy" = OFF trong BotFather
     (hoặc dùng /command@YourBotName trong group)
"""
import asyncio
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

from app.notifier.report_builder import (
    build_company_report,
    build_overview_report,
    build_top_report,
    get_all_companies,
    search_articles,
)
from app.notifier.alert_config import (
    get_watchlist,
    add_ticker,
    remove_ticker,
    reset_to_all,
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

        "<b>🔔 Thông báo cá nhân (vào DM của bạn):</b>\n"
        "  /subscribe       — Đăng ký nhận thông báo\n"
        "  /unsubscribe     — Tắt thông báo\n"
        "  /myalerts        — Xem & chỉnh cấu hình của bạn\n"
        "  /only <code>VIC SBT</code>   — Chỉ nhận tin của ticker cụ thể\n"
        "  /alltickers      — Nhận tin của tất cả công ty\n"
        "  /neg_only        — Chỉ nhận tin 🔴 tiêu cực\n"
        "  /pos_neg         — Nhận cả 🟢 tích cực + 🔴 tiêu cực\n\n"

        "<b>📊 Tra cứu báo cáo:</b>\n"
        "  /report <code>TICKER</code> <i>[24h|48h|7d]</i> — Báo cáo 1 công ty\n"
        "  /all <i>[24h|48h|7d]</i>    — Tổng quan tất cả công ty\n"
        "  /top <code>pos</code>|<code>neg</code> <i>[7d]</i>  — Top tin POS/NEG\n"
        "  /search <code>từ khóa</code> <i>[7d]</i>  — Tìm bài theo từ khóa\n"
        "  /list            — Danh sách ticker đang theo dõi\n"
        "  /export <i>[7d]</i>          — Xuất CSV về máy\n\n"

        "<b>🧠 Dạy bot (tự học):</b>\n"
        "  Bấm ✅/🟢/🔴/⚪ dưới mỗi tin để xác nhận / sửa nhãn\n"
        "  /fix <code>1234 pos|neg|neu</code> — Sửa nhãn bài #1234\n"
        "  /why <code>1234</code>      — Vì sao bot chấm vậy, % nghĩa là gì\n"
        "  /learn           — Độ chính xác hiện tại của bot\n"
        "  /learn now       — Tự học ngay (chat chính)\n\n"

        "<b>⚙️ Hệ thống:</b>\n"
        "  /status          — Trạng thái hệ thống\n"
        "  /ping            — Kiểm tra RSS feeds\n"
        "  /clear <i>[N]</i>            — Xóa N tin nhắn trong group\n\n"

        "<b>Ví dụ nhanh:</b>\n"
        "  <code>/subscribe</code>\n"
        "  <code>/only VIC DGC</code>\n"
        "  <code>/report SBT 48h</code>\n"
        "  <code>/search lợi nhuận giảm 7d</code>"
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
        f"<i>by dlk</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/search KEYWORD [24h|48h|7d] — tìm bài theo từ khóa."""
    if not ctx.args:
        await update.message.reply_text(
            "⚠️ Thiếu từ khóa. Ví dụ: <code>/search lợi nhuận tăng</code> hoặc <code>/search SBT 7d</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Phân tích args: từ khóa là tất cả trừ arg cuối nếu là khoảng thời gian
    args = ctx.args
    if args and re.match(r"^\d+[hd]$", args[-1], re.IGNORECASE):
        hours = _parse_hours(args[-1])
        keyword = " ".join(args[:-1])
    else:
        hours = 48
        keyword = " ".join(args)

    if not keyword:
        await update.message.reply_text("⚠️ Thiếu từ khóa.", parse_mode=ParseMode.HTML)
        return

    wait_msg = await update.message.reply_text(
        f"🔍 Đang tìm «<b>{keyword}</b>»...", parse_mode=ParseMode.HTML
    )
    result = await search_articles(keyword, hours)
    await wait_msg.delete()
    await update.message.reply_text(
        result,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/ping — kiểm tra trạng thái tất cả RSS feeds."""
    import time
    import httpx as _httpx
    from app.config import load_sources

    sources = [s for s in load_sources() if s.get("active") and s.get("type") != "google_rss"]
    wait_msg = await update.message.reply_text(
        f"⏳ Đang kiểm tra {len(sources)} feeds...", parse_mode=ParseMode.HTML
    )

    lines = ["🔍 <b>KIỂM TRA RSS FEEDS</b>\n"]
    ok_count = 0
    async with _httpx.AsyncClient() as client:
        for src in sources:
            t0 = time.monotonic()
            try:
                resp = await client.head(
                    src["url"], timeout=8, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; TheEye/1.0)"},
                )
                ms = int((time.monotonic() - t0) * 1000)
                if resp.status_code < 400:
                    status = "✅"
                    ok_count += 1
                else:
                    status = f"⚠️ {resp.status_code}"
                lines.append(f"{status} {src['name'][:45]}  <i>({ms}ms)</i>")
            except Exception as e:
                ms = int((time.monotonic() - t0) * 1000)
                lines.append(f"❌ {src['name'][:45]}  <i>{str(e)[:40]}</i>")

    lines.append(f"\n<b>{ok_count}/{len(sources)}</b> feeds hoạt động bình thường.")
    await wait_msg.delete()
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/export [24h|48h|7d] — xuất CSV bài báo gần đây."""
    import csv
    import io
    from app.db import AsyncSessionLocal
    from app.db.models import ArticleMeta, Company
    from sqlalchemy import select

    hours = _parse_hours(ctx.args[0] if ctx.args else None) if ctx.args else 48

    wait_msg = await update.message.reply_text(
        f"⏳ Đang xuất dữ liệu {hours}h qua...", parse_mode=ParseMode.HTML
    )

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta, Company)
            .join(Company, ArticleMeta.company_id == Company.id)
            .where(ArticleMeta.published_at >= since)
            .order_by(ArticleMeta.published_at.desc())
        )
        rows = result.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ticker", "company", "sentiment", "score", "published_at", "title", "url"])
    for art, company in rows:
        writer.writerow([
            company.ticker,
            company.name,
            art.sentiment or "",
            f"{(art.sentiment_score or 0):.2f}",
            art.published_at.strftime("%Y-%m-%d %H:%M UTC"),
            art.title,
            art.url,
        ])

    label_range = f"{hours}h" if hours < 48 else f"{hours // 24} ngày"
    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM để Excel đọc được tiếng Việt
    filename = f"the-eye-{datetime.now().strftime('%Y%m%d-%H%M')}.csv"

    await wait_msg.delete()
    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"📊 <b>{len(rows)} bài</b> trong {label_range} qua",
        parse_mode=ParseMode.HTML,
    )
    log.info(f"[bot] /export {hours}h → {len(rows)} articles → {filename}")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/watch TICKER — thêm ticker vào danh sách nhận Heading News."""
    if not ctx.args:
        await update.message.reply_text(
            "⚠️ Thiếu ticker. Ví dụ: <code>/watch VIC</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    ticker = _normalize_ticker(ctx.args[0])
    add_ticker(ticker)
    watchlist = get_watchlist()
    tickers_str = " · ".join(f"<b>{t}</b>" for t in watchlist) if watchlist else "—"
    await update.message.reply_text(
        f"✅ Đã thêm <b>{ticker}</b> vào danh sách Heading News.\n"
        f"📋 Đang theo dõi: {tickers_str}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/unwatch TICKER — xóa ticker khỏi danh sách Heading News."""
    if not ctx.args:
        await update.message.reply_text(
            "⚠️ Thiếu ticker. Ví dụ: <code>/unwatch VIC</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    ticker = _normalize_ticker(ctx.args[0])
    removed = remove_ticker(ticker)
    if not removed:
        watchlist = get_watchlist()
        if watchlist is None:
            msg = (
                f"ℹ️ <b>{ticker}</b> không nằm trong danh sách cụ thể "
                f"(hiện đang nhận Heading News từ <b>TẤT CẢ</b> ticker).\n"
                f"Dùng <code>/watch TICKER</code> để chuyển sang chế độ lọc."
            )
        else:
            msg = f"⚠️ <b>{ticker}</b> không có trong danh sách."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    watchlist = get_watchlist()
    if watchlist:
        tickers_str = " · ".join(f"<b>{t}</b>" for t in watchlist)
        msg = f"✅ Đã xóa <b>{ticker}</b>.\n📋 Còn lại: {tickers_str}"
    else:
        msg = (
            f"✅ Đã xóa <b>{ticker}</b>.\n"
            f"⚠️ Danh sách trống — <b>không có ticker nào</b> nhận Heading News.\n"
            f"Dùng <code>/watchall</code> để nhận từ tất cả."
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_watchall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/watchall — nhận Heading News từ tất cả ticker (reset về mặc định)."""
    reset_to_all()
    await update.message.reply_text(
        "✅ Đã reset: nhận <b>Heading News từ TẤT CẢ ticker</b>.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_watching(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/watching — xem cấu hình Heading News hiện tại."""
    watchlist = get_watchlist()
    if watchlist is None:
        text = (
            "🔔 <b>HEADING NEWS — Cấu hình hiện tại</b>\n\n"
            "Chế độ: <b>TẤT CẢ ticker</b>\n"
            "<i>Nhận ngay khi bất kỳ công ty nào có tin POS/NEG.</i>\n\n"
            "Lệnh:\n"
            "  <code>/watch TICKER</code>   — chỉ theo dõi ticker cụ thể\n"
            "  <code>/unwatch TICKER</code> — bỏ theo dõi\n"
            "  <code>/watchall</code>       — quay lại chế độ tất cả"
        )
    elif not watchlist:
        text = (
            "🔕 <b>HEADING NEWS — Cấu hình hiện tại</b>\n\n"
            "Chế độ: <b>TẮT</b> (danh sách trống)\n"
            "<i>Không có ticker nào nhận Heading News tức thì.</i>\n\n"
            "Dùng <code>/watch TICKER</code> để thêm hoặc <code>/watchall</code> để nhận tất cả."
        )
    else:
        tickers_str = "\n".join(f"  • <b>{t}</b>" for t in watchlist)
        text = (
            f"🔔 <b>HEADING NEWS — Cấu hình hiện tại</b>\n\n"
            f"Chế độ: <b>Lọc theo ticker</b>\n"
            f"{tickers_str}\n\n"
            f"Lệnh:\n"
            f"  <code>/watch TICKER</code>   — thêm ticker\n"
            f"  <code>/unwatch TICKER</code> — bỏ ticker\n"
            f"  <code>/watchall</code>       — nhận từ tất cả"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/clear [N] — xóa N tin nhắn gần đây trong chat (mặc định 50, tối đa 200)."""
    args = ctx.args
    try:
        limit = min(int(args[0]), 200) if args else 50
    except (ValueError, IndexError):
        limit = 50

    chat_id = update.effective_chat.id
    current_msg_id = update.message.message_id

    try:
        await update.message.delete()
    except Exception:
        pass

    deleted = 0
    for msg_id in range(current_msg_id - 1, max(0, current_msg_id - limit - 1), -1):
        try:
            await ctx.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            deleted += 1
        except Exception:
            pass

    confirm = await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"🗑 Đã xóa <b>{deleted}</b> tin nhắn.",
        parse_mode=ParseMode.HTML,
    )
    await asyncio.sleep(3)
    try:
        await confirm.delete()
    except Exception:
        pass


# ─── Subscribe commands ─────────────────────────────────────────

async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/subscribe — đăng ký nhận thông báo vào chat riêng."""
    from app.notifier.subscriber import subscribe, format_subscriber_config, get_subscriber

    user = update.effective_user
    chat_id = update.effective_chat.id

    is_new, status = await subscribe(
        chat_id=chat_id,
        username=user.username,
        first_name=user.first_name,
    )

    if status == "already_active":
        sub = await get_subscriber(chat_id)
        await update.message.reply_text(
            f"ℹ️ Bạn đã đăng ký rồi.\n\n{format_subscriber_config(sub)}",
            parse_mode=ParseMode.HTML,
        )
    elif status == "reactivated":
        sub = await get_subscriber(chat_id)
        await update.message.reply_text(
            f"✅ Đã bật lại thông báo!\n\n{format_subscriber_config(sub)}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"✅ <b>Đăng ký thành công!</b>\n\n"
            f"Mặc định bạn sẽ nhận thông báo 🔴 <b>tiêu cực</b> về <b>NAF</b>.\n\n"
            f"<b>Tuỳ chỉnh thêm:</b>\n"
            f"  /only <code>VIC SBT</code>  — theo dõi ticker khác\n"
            f"  /alltickers           — nhận tin của tất cả công ty\n"
            f"  /pos_neg              — nhận cả tin tích cực\n"
            f"  /myalerts             — xem cấu hình của bạn\n"
            f"  /unsubscribe          — tắt thông báo\n\n"
            f"<i>Dùng /help để xem tất cả lệnh.</i>",
            parse_mode=ParseMode.HTML,
        )
        log.info(f"[bot] New subscriber: {user.username or user.first_name} (chat_id={chat_id})")


async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/unsubscribe — tắt thông báo cá nhân."""
    from app.notifier.subscriber import unsubscribe as do_unsubscribe

    chat_id = update.effective_chat.id
    ok = await do_unsubscribe(chat_id)

    if ok:
        await update.message.reply_text(
            "✅ Đã tắt thông báo. Bạn vẫn dùng được các lệnh tra cứu.\n"
            "Gõ /subscribe để bật lại bất cứ lúc nào.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            "ℹ️ Bạn chưa đăng ký hoặc đã tắt trước đó.\n"
            "Gõ /subscribe để đăng ký.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_myalerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/myalerts — xem và chỉnh cấu hình thông báo cá nhân."""
    from app.notifier.subscriber import get_subscriber, format_subscriber_config

    chat_id = update.effective_chat.id
    sub = await get_subscriber(chat_id)

    if not sub or not sub.active:
        await update.message.reply_text(
            "ℹ️ Bạn chưa đăng ký nhận thông báo cá nhân.\n"
            "Gõ /subscribe để bắt đầu.",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        format_subscriber_config(sub),
        parse_mode=ParseMode.HTML,
    )


async def cmd_only(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/only VIC SBT — chỉ nhận tin của những ticker này."""
    from app.notifier.subscriber import get_subscriber, set_tickers

    chat_id = update.effective_chat.id
    sub = await get_subscriber(chat_id)
    if not sub or not sub.active:
        await update.message.reply_text(
            "⚠️ Bạn chưa đăng ký. Dùng /subscribe trước.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not ctx.args:
        await update.message.reply_text(
            "⚠️ Thiếu ticker. Ví dụ: <code>/only VIC SBT DGC</code>\n"
            "Dùng /alltickers để nhận tin của tất cả công ty.",
            parse_mode=ParseMode.HTML,
        )
        return

    tickers = [t.upper() for t in ctx.args]
    await set_tickers(chat_id, tickers)
    tickers_str = " · ".join(f"<b>{t}</b>" for t in tickers)
    await update.message.reply_text(
        f"✅ Chỉ nhận thông báo từ: {tickers_str}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_alltickers(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/alltickers — nhận thông báo từ tất cả công ty."""
    from app.notifier.subscriber import get_subscriber, set_tickers

    chat_id = update.effective_chat.id
    sub = await get_subscriber(chat_id)
    if not sub or not sub.active:
        await update.message.reply_text("⚠️ Bạn chưa đăng ký. Dùng /subscribe trước.")
        return

    await set_tickers(chat_id, None)
    await update.message.reply_text(
        "✅ Nhận thông báo từ <b>tất cả</b> công ty.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_neg_only(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/neg_only — chỉ nhận tin tiêu cực."""
    from app.notifier.subscriber import get_subscriber, set_sentiments

    chat_id = update.effective_chat.id
    sub = await get_subscriber(chat_id)
    if not sub or not sub.active:
        await update.message.reply_text("⚠️ Bạn chưa đăng ký. Dùng /subscribe trước.")
        return

    await set_sentiments(chat_id, ["NEG"])
    await update.message.reply_text(
        "✅ Chỉ nhận tin 🔴 <b>tiêu cực</b> (NEG).",
        parse_mode=ParseMode.HTML,
    )


async def cmd_pos_neg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/pos_neg — nhận cả tin tích cực và tiêu cực."""
    from app.notifier.subscriber import get_subscriber, set_sentiments

    chat_id = update.effective_chat.id
    sub = await get_subscriber(chat_id)
    if not sub or not sub.active:
        await update.message.reply_text("⚠️ Bạn chưa đăng ký. Dùng /subscribe trước.")
        return

    await set_sentiments(chat_id, ["POS", "NEG"])
    await update.message.reply_text(
        "✅ Nhận tin 🟢 <b>tích cực</b> + 🔴 <b>tiêu cực</b> (POS + NEG).",
        parse_mode=ParseMode.HTML,
    )


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

    # Tra cứu
    app.add_handler(CommandHandler("start",       cmd_subscribe))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("report",      cmd_report))
    app.add_handler(CommandHandler("all",         cmd_all))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("top",         cmd_top))
    app.add_handler(CommandHandler("list",        cmd_list))
    app.add_handler(CommandHandler("search",      cmd_search))
    app.add_handler(CommandHandler("ping",        cmd_ping))
    app.add_handler(CommandHandler("export",      cmd_export))

    # Watchlist (alert_config — toàn group)
    app.add_handler(CommandHandler("watch",       cmd_watch))
    app.add_handler(CommandHandler("unwatch",     cmd_unwatch))
    app.add_handler(CommandHandler("watchall",    cmd_watchall))
    app.add_handler(CommandHandler("watching",    cmd_watching))

    # Subscribe (cá nhân — nhận vào DM)
    app.add_handler(CommandHandler("subscribe",   cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("myalerts",    cmd_myalerts))
    app.add_handler(CommandHandler("only",        cmd_only))
    app.add_handler(CommandHandler("alltickers",  cmd_alltickers))
    app.add_handler(CommandHandler("neg_only",    cmd_neg_only))
    app.add_handler(CommandHandler("pos_neg",     cmd_pos_neg))

    # Tiện ích
    app.add_handler(CommandHandler("clear",       cmd_clear))

    # Tự học — người dùng dạy bot, xem giải thích & độ chính xác
    from app.notifier.learning_commands import (
        cb_feedback, cb_feedback_reopen, cmd_fix, cmd_learn, cmd_why,
    )
    app.add_handler(CallbackQueryHandler(cb_feedback,        pattern=r"^fb:"))
    app.add_handler(CallbackQueryHandler(cb_feedback_reopen, pattern=r"^fbx:"))
    app.add_handler(CommandHandler("fix",         cmd_fix))
    app.add_handler(CommandHandler("why",         cmd_why))
    app.add_handler(MessageHandler(filters.Regex(r"^/why_\d+"), cmd_why))
    app.add_handler(CommandHandler("learn",       cmd_learn))

    return app


async def set_bot_commands(application: Application) -> None:
    """Đăng ký danh sách lệnh hiện trên Telegram UI."""
    commands = [
        BotCommand("subscribe",   "Đăng ký nhận thông báo cá nhân vào DM"),
        BotCommand("unsubscribe", "Tắt thông báo cá nhân"),
        BotCommand("myalerts",    "Xem & chỉnh cấu hình thông báo của bạn"),
        BotCommand("report",      "Báo cáo công ty: /report VIC [24h|48h|7d]"),
        BotCommand("all",         "Tổng quan tất cả công ty"),
        BotCommand("top",         "Top tin: /top pos|neg [7d]"),
        BotCommand("search",      "Tìm bài: /search từ khóa [7d]"),
        BotCommand("export",      "Xuất CSV dữ liệu"),
        BotCommand("list",        "Danh sách công ty đang theo dõi"),
        BotCommand("ping",        "Kiểm tra RSS feeds"),
        BotCommand("status",      "Trạng thái hệ thống"),
        BotCommand("learn",       "Bot tự học tới đâu: độ chính xác, ý nghĩa %"),
        BotCommand("why",         "Vì sao bot chấm 1 bài: /why 1234"),
        BotCommand("fix",         "Sửa nhãn để dạy bot: /fix 1234 pos|neg|neu"),
        BotCommand("help",        "Hướng dẫn đầy đủ"),
    ]
    await application.bot.set_my_commands(commands)
    log.info("[bot] Commands registered on Telegram")


async def start_polling(application: Application) -> None:
    """Khởi động bot polling — gọi từ scheduler.py."""
    await application.initialize()
    await set_bot_commands(application)
    await application.start()
    await application.updater.start_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,       # bỏ qua tin nhắn cũ khi restart
    )
    log.info("[bot] Polling started")


async def stop_polling(application: Application) -> None:
    """Dừng bot gracefully."""
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    log.info("[bot] Stopped")
