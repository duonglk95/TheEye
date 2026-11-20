"""
Scheduler — gắn kết tất cả jobs:
  - Poll RSS mỗi 5 phút → classify → gửi ngay nếu NEG
  - Retry unnotified NEG mỗi 15 phút (phục hồi sau Telegram outage)
  - Scrape full content mỗi 10 phút → ĐỌC LẠI TOÀN BÀI → báo ngay nếu thành NEG
  - Tự học mỗi đêm 02:30 (train mô hình ML từ phản hồi người dùng + luật)
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


async def job_scrape_and_deep_read():
    """
    Scrape thân bài → đọc lại toàn bài.
    Tin có tiêu đề trung tính nhưng thân bài rõ tốt/xấu sẽ đổi nhãn tại đây:
      → NEG: gửi cảnh báo ngay   → POS: vào digest kế tiếp (notified vẫn False)
    """
    from app.collector.scraper import scrape_pending
    from app.classifier.classifier import deep_read_pending
    from app.notifier.telegram import send_immediate

    await scrape_pending(limit=20)
    changes = await deep_read_pending(limit=50)
    for c in changes:
        if c.new == "NEG" and not c.notified:
            await send_immediate(c.article_id)
            log.info(f"Deep read: #{c.article_id} {c.old}→NEG, alert sent")


async def job_self_learning():
    """Vòng tự học hằng đêm — chạy ngầm, chỉ ghi log (không gửi vào group)."""
    from app.learning.trainer import run_learning

    try:
        report = await run_learning()
        log.info(f"[learn] v{report.get('version')} {report.get('decision')}: "
                 f"{report.get('note') or report.get('reason', '')}")
    except Exception as e:
        log.exception(f"[learn] failed: {e}")


async def job_send_digest():
    """Gửi digest POS tổng hợp 2 tiếng/lần."""
    from app.notifier.telegram import send_digest
    await send_digest()


async def start_scheduler():
    from app.notifier.bot_handler import build_application, start_polling, stop_polling

    from app.classifier.model_store import refresh_active
    await refresh_active()      # nạp mô hình ML đã học (nếu có) trước khi phân loại

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

    # Scrape full content + đọc lại toàn bài: mỗi 10 phút
    scheduler.add_job(
        job_scrape_and_deep_read,
        trigger=IntervalTrigger(minutes=10),
        id="scrape_and_deep_read",
        name="Scrape & Deep Read",
        max_instances=1,
        misfire_grace_time=120,
    )

    # Tự học: 02:30 mỗi đêm (ít tin, CPU rảnh)
    scheduler.add_job(
        job_self_learning,
        trigger=CronTrigger(hour=2, minute=30),
        id="self_learning",
        name="Self-learning (train ML model)",
        max_instances=1,
        misfire_grace_time=3600,
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
    log.info("  - Scrape + deep read:   every 10 min → re-label from full article")
    log.info("  - Self-learning:        daily 02:30 ICT")
    log.info("  - POS digest:           every 2h (08:00–22:00 ICT)")

    await start_polling(bot_app)
    log.info("  - Telegram Bot:         polling started")

    # API nhỏ cho Scheduled Task của Claude Code chấm nhãn hằng tuần (bot không gọi LLM)
    from app.web.api import start_api
    try:
        api_runner = await start_api()
    except Exception as e:      # API lỗi không được làm sập bot
        log.error(f"[api] không khởi động được: {e}")
        api_runner = None

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        await stop_polling(bot_app)
        if api_runner:
            await api_runner.cleanup()
        log.info("Scheduler + Bot stopped.")
