"""
Ai là admin (chủ bot Bao)?

Chỉ admin được chấm nhãn tin (nút 🔴/⚪/🟢, /fix) và xem giải thích (/why).
Người dùng thường chỉ thấy giao diện xem tin — không có nút chấm, không có thông tin training.

Cấu hình:
  ADMIN_USER_IDS = "123456789,987654321"   (Telegram user id, phân cách dấu phẩy)
  Không đặt → dùng TELEGRAM_CHAT_ID nếu đó là chat riêng (số dương = user id của chủ bot).
"""
import os


def admin_ids() -> set[int]:
    raw = os.environ.get("ADMIN_USER_IDS", "")
    ids = {int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit()}
    if not ids:
        chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        if chat.isdigit():          # số dương → chat riêng của chủ bot
            ids.add(int(chat))
    return ids


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) in admin_ids()


def is_admin_private_chat(chat_id: int | str | None) -> bool:
    """Chat riêng với admin (ở Telegram, chat riêng có chat_id = user_id). Group luôn False."""
    try:
        return chat_id is not None and int(chat_id) > 0 and int(chat_id) in admin_ids()
    except (TypeError, ValueError):
        return False
