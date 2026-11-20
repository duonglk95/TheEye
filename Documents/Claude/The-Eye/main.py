"""
The-Eye — entry point

Modes:
  python main.py          → chạy background service (Railway)
  python main.py --tui    → mở TUI terminal interface
  python main.py --demo   → TUI với dữ liệu demo (không cần DB)
"""
import sys
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("the-eye")

# Không để token bot / mật khẩu DB lọt vào log (httpx log cả URL chứa token)
from app.log_redact import install_redaction  # noqa: E402
install_redaction()


async def run_service():
    """Chế độ background service — dùng trên Railway."""
    from app.db import ping
    from app.db.migrate import apply_migrations
    from app.collector.scheduler import start_scheduler
    log.info("Starting The-Eye service...")
    await ping()
    log.info("Database connected.")
    await apply_migrations()

    # Đồng bộ companies.yaml / sources.yaml vào DB (chỉ thêm/cập nhật, không xoá công ty có sẵn trong DB)
    from app.db.seed import main as seed_from_yaml
    try:
        await seed_from_yaml()
    except Exception as e:      # YAML lỗi không được làm sập bot
        log.error(f"seed from yaml failed: {e}")

    # Bài không còn khớp từ khoá công ty đang gắn (VD sau khi sửa từ khoá DGC) → gắn lại / bỏ gắn
    from app.collector.rss_fetcher import rematch_existing
    try:
        await rematch_existing()
    except Exception as e:
        log.error(f"rematch_existing failed: {e}")
    await start_scheduler()


def run_tui(demo: bool = False):
    """Chế độ TUI terminal — dùng local."""
    from app.tui.app import TheEyeApp
    app = TheEyeApp()
    app.run()


if __name__ == "__main__":
    if "--tui" in sys.argv or "--demo" in sys.argv:
        run_tui(demo="--demo" in sys.argv)
    else:
        asyncio.run(run_service())
