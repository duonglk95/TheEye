import logging
import sys

from app.log_redact import RedactFilter, redact

FAKE_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz_fake-123"


def test_redacts_bot_token_in_url():
    out = redact(f"POST https://api.telegram.org/bot{FAKE_TOKEN}/getUpdates 409")
    assert "ABCdef" not in out and "bot***" in out


def test_redacts_db_password():
    assert redact("postgresql://postgres:s3cret@host:5432/db") == "postgresql://postgres:***@host:5432/db"


def test_filter_redacts_args_and_tracebacks():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "send failed: %s",
                               (f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage",), None)
    try:
        raise RuntimeError(f"Client error for url https://api.telegram.org/bot{FAKE_TOKEN}/x")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    RedactFilter().filter(record)
    assert "ABCdef" not in record.getMessage()
    assert "ABCdef" not in record.exc_text
