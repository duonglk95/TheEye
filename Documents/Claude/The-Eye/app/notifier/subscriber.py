"""
Subscriber manager — quản lý người dùng đăng ký nhận thông báo.

Luồng:
  User gõ /subscribe  → thêm vào bảng subscribers
  User gõ /unsubscribe → đánh dấu active=False
  User gõ /myalerts   → xem cấu hình của mình
  User gõ /only VIC NAF → chỉ nhận tin về 2 ticker này
  User gõ /neg_only   → chỉ nhận tin tiêu cực
  User gõ /pos_neg    → nhận cả POS và NEG (mặc định)
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import Subscriber

log = logging.getLogger(__name__)

SENTIMENT_ICON = {"POS": "🟢", "NEG": "🔴", "NEU": "⚪"}


async def subscribe(
    chat_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> tuple[bool, str]:
    """
    Đăng ký nhận thông báo.
    Returns: (is_new, message)
    """
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(Subscriber).where(Subscriber.chat_id == chat_id)
        )

        if existing:
            if existing.active:
                return False, "already_active"
            # Kích hoạt lại
            existing.active = True
            existing.last_seen_at = datetime.now(timezone.utc)
            await session.commit()
            return False, "reactivated"

        session.add(Subscriber(
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            tickers=["NAF"],      # mặc định: chỉ NAF
            sentiments=["NEG"],   # mặc định: chỉ NEG tức thì, POS qua digest
            active=True,
            subscribed_at=datetime.now(timezone.utc),
        ))
        await session.commit()
        return True, "new"


async def unsubscribe(chat_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Subscriber)
            .where(Subscriber.chat_id == chat_id)
            .where(Subscriber.active == True)  # noqa
            .values(active=False)
        )
        await session.commit()
        return result.rowcount > 0


async def get_subscriber(chat_id: int) -> Subscriber | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            select(Subscriber).where(Subscriber.chat_id == chat_id)
        )


async def get_all_active() -> list[Subscriber]:
    async with AsyncSessionLocal() as session:
        result = await session.scalars(
            select(Subscriber).where(Subscriber.active == True)  # noqa
        )
        return list(result.all())


async def set_tickers(chat_id: int, tickers: list[str] | None) -> bool:
    """None = tất cả ticker; list = chỉ những ticker đó."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Subscriber)
            .where(Subscriber.chat_id == chat_id)
            .values(
                tickers=[t.upper() for t in tickers] if tickers else None,
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result.rowcount > 0


async def set_sentiments(chat_id: int, sentiments: list[str]) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Subscriber)
            .where(Subscriber.chat_id == chat_id)
            .values(sentiments=sentiments)
        )
        await session.commit()
        return result.rowcount > 0


async def touch(chat_id: int) -> None:
    """Cập nhật last_seen_at."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Subscriber)
            .where(Subscriber.chat_id == chat_id)
            .values(last_seen_at=datetime.now(timezone.utc))
        )
        await session.commit()


async def count_active() -> int:
    from sqlalchemy import func
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(Subscriber)
            .where(Subscriber.active == True)  # noqa
        ) or 0


def format_subscriber_config(sub: Subscriber) -> str:
    """Format cấu hình của 1 subscriber thành text Telegram."""
    if sub.tickers:
        ticker_str = " · ".join(f"<b>{t}</b>" for t in sub.tickers)
    else:
        ticker_str = "<b>Tất cả</b> (SBT · DGC · NAF · VIC · CTD)"

    sent_icons = " · ".join(
        f"{SENTIMENT_ICON.get(s, '⚪')}<b>{s}</b>"
        for s in (sub.sentiments or ["NEG"])
    )

    since = (
        sub.subscribed_at.strftime("%d/%m/%Y")
        if sub.subscribed_at else "—"
    )

    return (
        f"🔔 <b>CẤU HÌNH THÔNG BÁO CÁ NHÂN</b>\n\n"
        f"  Trạng thái  : {'✅ Đang nhận' if sub.active else '❌ Đã tắt'}\n"
        f"  Công ty     : {ticker_str}\n"
        f"  Loại tin    : {sent_icons}\n"
        f"  Đăng ký từ  : {since}\n\n"
        f"<b>Thay đổi:</b>\n"
        f"  /only <code>VIC SBT</code>  — chỉ nhận tin của ticker cụ thể\n"
        f"  /alltickers       — nhận tin của tất cả công ty\n"
        f"  /neg_only         — chỉ nhận tin 🔴 tiêu cực\n"
        f"  /pos_neg          — nhận cả 🟢 tích cực và 🔴 tiêu cực\n"
        f"  /unsubscribe      — tắt toàn bộ thông báo"
    )
