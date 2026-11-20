"""
Chặn lộ bí mật trong log.

Telegram đặt token ngay trong URL (api.telegram.org/bot<TOKEN>/sendMessage), nên:
  - httpx/httpcore ở mức INFO ghi lại mọi URL request → lộ token
  - thông báo lỗi của httpx (HTTPStatusError, ConnectError...) cũng chứa URL → lộ token
Giải pháp 2 lớp:
  1. Hạ httpx/httpcore xuống WARNING (không log từng request)
  2. Filter trên mọi handler: thay token bot và mật khẩu trong DATABASE_URL bằng ***
"""
import logging
import os
import re

_BOT_TOKEN_RE = re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}")
_DSN_PASSWORD_RE = re.compile(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@")


def redact(text: str) -> str:
    text = _BOT_TOKEN_RE.sub("bot***", text)
    text = _DSN_PASSWORD_RE.sub(r"\1***@", text)
    for name in ("TELEGRAM_BOT_TOKEN",):
        secret = os.environ.get(name)
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def install_redaction() -> None:
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    f = RedactFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(f)
