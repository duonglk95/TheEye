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


async def run_service():
    """Chế độ background service — dùng trên Railway."""
    from app.db import ping
    from app.db.migrate import apply_migrations
    from app.collector.scheduler import start_scheduler
    log.info("Starting The-Eye service...")
    await ping()
    log.info("Database connected.")
    await apply_migrations()
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
