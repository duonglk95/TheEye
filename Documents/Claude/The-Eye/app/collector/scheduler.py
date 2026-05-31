"""
Scheduler — gắn kết tất cả jobs:
  - Poll RSS mỗi 5 phút
  - Scrape full content background mỗi 10 phút
  - Gửi digest Telegram mỗi 2 tiếng
  - POS/NEG → gửi ngay sau khi classify
  - Telegram Bot polling (chạy song song)
"""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


async def job_poll_and_classify():
    """Poll feeds → classify → gửi ngay nếu POS/NEG."""
    from app.collector.rss_fetcher import poll_feeds
    from app.classifier.classifier import classify_batch
    from app.notifier.telegram import send_immediate

    new_ids = await poll_feeds()
    if not new_ids:
        return

    results = await classify_batch(new_ids)

    # Gửi ngay các tin POS/NEG
    urgent = [aid for aid, label in results.items() if label in ("POS", "NEG")]
    for article_id in urgent:
        await send_immediate(article_id)
        log.info(f"Immediate alert sent for article #{article_id} ({results[article_id]})")


async def job_scrape_pending():
    """Scrape full content background — phục vụ Phase 2."""
    from app.collector.scraper import scrape_pending
    await scrape_pending(limit=20)


async def job_send_digest():
    """Gửi digest tổng hợp 2 tiếng/lần."""
    from app.notifier.telegram import send_digest
    await send_digest()


async def start_scheduler():
    from app.notifier.bot_handler import build_application, start_polling, stop_polling

    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    bot_app = build_application()

    # Poll RSS + classify + immediate alert: mỗi 5 phút
    scheduler.add_job(
        job_poll_and_classify,
        trigger=IntervalTrigger(minutes=5),
        id="poll_and_classify",
        name="Poll RSS & Classify",
        max_instances=1,
        misfire_grace_time=60,
    )

    # Scrape full content: mỗi 10 phút
    scheduler.add_job(
        job_scrape_pending,
        trigger=IntervalTrigger(minutes=10),
        id="scrape_pending",
        name="Scrape Article Content",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Digest: mỗi 2 tiếng, vào đầu giờ chẵn (8h–22h)
    scheduler.add_job(
        job_send_digest,
        trigger=CronTrigger(hour="8,10,12,14,16,18,20,22", minute=0),
        id="send_digest",
        name="Send Telegram Digest",
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info("Scheduler started.")
    log.info("  - Poll RSS & classify: every 5 min")
    log.info("  - Scrape content:      every 10 min")
    log.info("  - Telegram digest:     every 2h (08:00–22:00 ICT)")

    # Khởi động Telegram Bot polling song song
    await start_polling(bot_app)
    log.info("  - Telegram Bot:        polling started")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        await stop_polling(bot_app)
        log.info("Scheduler + Bot stopped.")
