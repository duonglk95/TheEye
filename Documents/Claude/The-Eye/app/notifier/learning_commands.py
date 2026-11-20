"""
Lệnh Telegram cho vòng tự học — CHỈ ADMIN (chủ bot) dùng được; người dùng thường không thấy:
  nút ✅/🟢/🔴/⚪ dưới mỗi tin   — dạy bot (callback "fb:<id>:<LABEL|OK>")
  /fix <id> pos|neg|neu          — sửa nhãn bằng lệnh
  /why <id>  hoặc  /why_<id>     — vì sao bot chấm như vậy, con số % nghĩa là gì
"""
import html as html_lib
import logging
import os
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.classifier import model_store
from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, Company
from app.learning.feedback import record_feedback
from app.notifier.admin import is_admin
from app.notifier.formatting import VN_TZ, confidence_text, esc, short_title

log = logging.getLogger(__name__)

ICON = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}
NAME = {"POS": "TÍCH CỰC", "NEG": "TIÊU CỰC", "NEU": "TRUNG LẬP"}
NAME_SHORT = {"POS": "Tích cực", "NEG": "Tiêu cực", "NEU": "Trung lập"}
_LABEL_ALIASES = {"pos": "POS", "tot": "POS", "tốt": "POS", "neg": "NEG", "xau": "NEG", "xấu": "NEG",
                  "neu": "NEU", "trung": "NEU", "trunglap": "NEU"}


def _user(update: Update) -> tuple[int, str | None]:
    u = update.effective_user
    return (u.id, u.username or u.first_name) if u else (0, None)


# ─── Feedback ────────────────────────────────────────────────────

async def _deny_callback(update: Update) -> bool:
    """True nếu người bấm không phải admin (đã trả lời từ chối)."""
    if is_admin(_user(update)[0]):
        return False
    await update.callback_query.answer("Chỉ admin của Bao mới chấm nhãn được.", show_alert=True)
    return True


async def cb_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_callback(update):
        return
    query = update.callback_query
    m = re.fullmatch(r"fb:(\d+):(OK|POS|NEG|NEU)", query.data or "")
    if not m:
        await query.answer()
        return
    article_id, choice = int(m.group(1)), m.group(2)

    if choice == "OK":
        async with AsyncSessionLocal() as session:
            art = await session.get(ArticleMeta, article_id)
        if art is None or not art.sentiment:
            await query.answer("Không tìm thấy bài", show_alert=True)
            return
        # "Đúng" = đồng ý với nhãn hiển thị trong tin, tức nhãn bot đoán lúc gửi
        # (nếu đã có người sửa, nhãn gốc nằm ở evidence.human.previous)
        label = ((art.sentiment_evidence or {}).get("human") or {}).get("previous") or art.sentiment
    else:
        label = choice

    uid, uname = _user(update)
    art = await record_feedback(article_id, label, uid, uname)
    if art is None:
        await query.answer("Không tìm thấy bài", show_alert=True)
        return
    await query.answer(f"Cảm ơn! Đã ghi nhận {ICON[label]} {NAME_SHORT[label]} — Bao sẽ học từ bài này.")
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📝 {ICON[label]} {NAME_SHORT[label]} · {uname or 'bạn'} · sửa",
                                 callback_data=f"fbx:{article_id}"),
        ]]))
    except Exception as e:      # tin quá cũ / không có quyền sửa
        log.debug(f"edit markup failed: {e}")


async def cb_feedback_reopen(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Bấm vào nút 'đã ghi nhận' → hiện lại bộ nút để sửa."""
    if await _deny_callback(update):
        return
    from app.notifier.formatting import feedback_keyboard
    query = update.callback_query
    m = re.fullmatch(r"fbx:(\d+)", query.data or "")
    await query.answer()
    if m:
        kb = feedback_keyboard(int(m.group(1)))["inline_keyboard"]
        await query.edit_message_reply_markup(InlineKeyboardMarkup(
            [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row] for row in kb]
        ))


async def cmd_fix(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/fix <id> pos|neg|neu — chỉ admin"""
    if not is_admin(_user(update)[0]):
        return          # im lặng với người dùng thường
    args = ctx.args or []
    label = _LABEL_ALIASES.get(args[1].lower()) if len(args) >= 2 else None
    if len(args) < 2 or not args[0].lstrip("#").isdigit() or not label:
        await update.message.reply_text(
            "Cách dùng: <code>/fix 1234 pos</code> (pos | neg | neu)\nSố id nằm cuối mỗi tin, dạng #1234.",
            parse_mode=ParseMode.HTML)
        return
    uid, uname = _user(update)
    art = await record_feedback(int(args[0].lstrip("#")), label, uid, uname)
    if art is None:
        await update.message.reply_text("Không tìm thấy bài này.")
        return
    await update.message.reply_text(
        f"📝 Đã ghi nhận bài #{art.id} là {ICON[label]} <b>{NAME[label]}</b>.\n"
        f"Bot sẽ học từ nhãn này ở lần tự học tiếp theo (02:30 hằng đêm).",
        parse_mode=ParseMode.HTML)


# ─── Explain ─────────────────────────────────────────────────────

def _reliability_for(score: float, metrics: dict) -> tuple[dict | None, str]:
    scope_key = "val_gold" if "val_gold" in metrics else "val"
    scope_name = "nhãn người dùng" if scope_key == "val_gold" else "nhãn luật đọc toàn bài"
    for b in metrics.get(scope_key, {}).get("bins", []):
        lo, hi = (int(x) / 100 for x in b["range"].rstrip("%").split("–"))
        if lo <= score < hi or (hi >= 1.0 and score >= lo):
            return b, scope_name
    return None, scope_name


async def explain_article(article_id: int) -> str:
    async with AsyncSessionLocal() as session:
        art = await session.get(ArticleMeta, article_id)
        company = await session.get(Company, art.company_id) if art else None
    if art is None:
        return "Không tìm thấy bài này."

    label = art.sentiment or "NEU"
    method = art.sentiment_method or ""
    ev = art.sentiment_evidence or {}
    conf = confidence_text(art.sentiment_score, method)
    ticker = company.ticker if company else "?"
    lines = [
        f"🔎 <b>Vì sao bot chấm bài #{art.id}</b>",
        f"<i>{esc(ticker)} · {esc(short_title(art.title, 100, strip_source=True))}</i>",
        "",
    ]

    if method == "human":
        h = ev.get("human", {})
        lines.append(f"{ICON[label]} <b>{NAME_SHORT[label]}</b> · do người dùng xác nhận ({esc(h.get('by', ''))})")
        prev = h.get("previous")
        if prev:
            verdict = "đúng ✅" if prev == label else "sai ❌ — bot sẽ học lại"
            lines.append(f"<i>Trước đó bot đoán {ICON.get(prev, '')} {NAME_SHORT.get(prev, prev)} → {verdict}</i>")
        return "\n".join(lines)

    if method == "llm":
        lines.append(f"{ICON[label]} <b>{NAME_SHORT[label]}</b> · do Claude đọc và chấm")
        return "\n".join(lines)

    depth = "đã đọc toàn bài" if art.read_depth == "full" else "mới đọc tiêu đề + sapo"
    engine = f"mô hình tự học {method.split('+')[0].replace('ml_', '')}" if method.startswith("ml_") else "từ khoá"
    lines.append(f"{ICON[label]} <b>{NAME_SHORT[label]} · {conf}</b>")
    lines.append(f"<i>{engine} · {depth}</i>")
    probs = ev.get("probs") or {}
    if probs:
        lines.append("Xác suất: " + " · ".join(
            f"{ICON[l]} {min(int(round(probs.get(l, 0) * 100)), 99)}%" for l in ("POS", "NEU", "NEG")))

    phrases = ev.get("phrases") or []
    body = ev.get("body")
    if phrases or body:
        lines += ["", "<b>Căn cứ</b>"]
        if phrases:
            lines.append(", ".join(f"“{esc(p)}”" for p in phrases[:6]))
        if body:
            lines.append(f"<i>Thân bài: {body['pos']}/{body['sentences']} câu tích cực, {body['neg']} câu tiêu cực</i>")

    lines += ["", f"<b>{conf} nghĩa là gì?</b>"]
    bundle = model_store.get_active()
    if method.startswith("ml_") and bundle is not None:
        b, scope = _reliability_for(art.sentiment_score or 0, bundle.metrics)
        if b:
            lines.append(f"Khi bot chấm {b['range']}, thực tế đúng <b>{int(round(b['actual'] * 100))}%</b> "
                         f"<i>({b['n']} bài kiểm tra, {scope})</i>.")
        else:
            lines.append("Xác suất đã hiệu chỉnh trên bài bot chưa từng học: nói 80% ≈ đúng 80%.")
    else:
        lines.append("Ước lượng theo từ khoá, <b>chưa kiểm chứng</b>: 1 từ khoá ≈ 50%, "
                     "nhiều bằng chứng cùng chiều thì cao hơn, trái chiều thì thấp hơn.")
        lines.append("<i>Khi đủ bài có nhãn, bot học và % sẽ được kiểm chứng.</i>")
    lines.append(f"\n<i>Sai? /fix {art.id} pos|neg|neu</i>")
    return "\n".join(lines)


async def cmd_why(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/why <id>  hoặc  /why_<id> — chỉ admin"""
    if not is_admin(_user(update)[0]):
        return
    text = update.message.text or ""
    m = re.match(r"^/why_(\d+)", text)
    raw = m.group(1) if m else ((ctx.args or [""])[0].lstrip("#") if ctx.args else "")
    if not raw.isdigit():
        await update.message.reply_text("Cách dùng: <code>/why 1234</code>", parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(await explain_article(int(raw)), parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)


# ─── Learning status ─────────────────────────────────────────────

# ─── Chấm 1 chạm (🔴 Xấu / ⚪ Thường / 🟢 Tốt) ───────────────────

async def cb_rate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from app.notifier.rating import (
        CB_RE, FACE, ids_from_markup, keyboard, rating_to_label, to_telegram_markup, vote_counts,
    )

    if await _deny_callback(update):
        return
    query = update.callback_query
    m = CB_RE.fullmatch(query.data or "")
    if not m:
        await query.answer()
        return
    article_id, rating = int(m.group(1)), int(m.group(2))
    uid, uname = _user(update)
    art = await record_feedback(article_id, rating_to_label(rating), uid, uname, rating=rating)
    if art is None:
        await query.answer("Không tìm thấy bài", show_alert=True)
        return
    await query.answer(f"Đã ghi nhận {FACE[rating]} — cảm ơn bạn!")

    ids = ids_from_markup(query.message.reply_markup) or [article_id]
    try:
        await query.edit_message_reply_markup(to_telegram_markup(keyboard(ids, await vote_counts(ids))))
    except Exception as e:      # "message is not modified" khi chạm lại cùng nút
        log.debug(f"edit markup skipped: {e}")


async def cb_noop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Nút số thứ tự bài — không làm gì."""
    await update.callback_query.answer()
