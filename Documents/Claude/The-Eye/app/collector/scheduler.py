"""
Scheduler — gắn kết tất cả jobs:
  - Poll RSS mỗi 5 phút → classify → gửi ngay nếu NEG
  - Retry unnotified NEG mỗi 15 phút (phục hồi sau Telegram outage)
  - Scrape full content background mỗi 10 phút
  - Gửi digest POS mỗi 2 tiếng (8h–22h)
  - Telegram Bot polling (chạy song song)
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


async def job_poll_and_classify():
    """Poll feeds → classify → gửi ngay nếu NEG."""
    from app.collector.rss_fetcher import poll_feeds
    from app.classifier.classifier import classify_batch
    from app.notifier.telegram import send_immediate

    new_ids = await poll_feeds()
    if not new_ids:
        return

    results = await classify_batch(new_ids)

    # Chỉ NEG gửi ngay lập tức; POS vào digest; NEU bỏ qua
    neg_ids = [aid for aid, label in results.items() if label == "NEG"]
    for article_id in neg_ids:
        await send_immediate(article_id)
        log.info(f"Immediate alert sent for article #{article_id} (NEG)")


async def job_retry_neg_alerts():
    """
    Retry unnotified NEG articles trong 4h qua.
    Phục hồi khi Telegram tạm thời down lúc gửi lần đầu.
    """
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    from app.db.models import ArticleMeta
    from app.notifier.telegram import send_immediate

    since = datetime.now(timezone.utc) - timedelta(hours=4)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ArticleMeta.id)
            .where(ArticleMeta.notified == False)       # noqa: E711
            .where(ArticleMeta.sentiment == "NEG")
            .where(ArticleMeta.fetched_at >= since)
            .where(ArticleMeta.classified_at != None)   # noqa: E711 — đã classify rồi
        )
        ids = [r[0] for r in result.fetchall()]

    if ids:
        log.info(f"[retry] Retrying {len(ids)} unnotified NEG articles")
        for article_id in ids:
            await send_immediate(article_id)


async def job_scrape_pending():
    """Scrape full content background — phục vụ Phase 2."""
    from app.collector.scraper import scrape_pending
    await scrape_pending(limit=20)


async def job_send_digest():
    """Gửi digest POS tổng hợp 2 tiếng/lần."""
    from app.notifier.telegram import send_digest
    await send_digest()


async def start_scheduler():
    from app.notifier.bot_handler import build_application, start_polling, stop_polling

    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    bot_app = build_application()

    # Poll RSS + classify + immediate NEG alert: mỗi 5 phút
    scheduler.add_job(
        job_poll_and_classify,
        trigger=IntervalTrigger(minutes=5),
        id="poll_and_classify",
        name="Poll RSS & Classify",
        max_instances=1,
        misfire_grace_time=60,
    )

    # Retry NEG alerts thất bại: mỗi 15 phút
    scheduler.add_job(
        job_retry_neg_alerts,
        trigger=IntervalTrigger(minutes=15),
        id="retry_neg_alerts",
        name="Retry Failed NEG Alerts",
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

    # Digest POS: mỗi 2 tiếng, vào đầu giờ chẵn (8h–22h)
    scheduler.add_job(
        job_send_digest,
        trigger=CronTrigger(hour="8,10,12,14,16,18,20,22", minute=0),
        id="send_digest",
        name="Send Telegram POS Digest",
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info("Scheduler started.")
    log.info("  - Poll RSS & classify:  every 5 min  → NEG immediate")
    log.info("  - Retry NEG alerts:     every 15 min → outage recovery")
    log.info("  - Scrape content:       every 10 min")
    log.info("  - POS digest:           every 2h (08:00–22:00 ICT)")

    await start_polling(bot_app)
    log.info("  - Telegram Bot:         polling started")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        await stop_polling(bot_app)
        log.info("Scheduler + Bot stopped.")
