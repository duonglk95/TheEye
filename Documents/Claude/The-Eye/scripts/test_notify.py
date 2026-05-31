"""
Test gửi Telegram — chạy trước khi deploy để kiểm tra bot token & chat_id.
Usage: python scripts/test_notify.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()


async def main():
    from app.notifier.telegram import _send
    ok = await _send(
        "✅ <b>The-Eye test notification</b>\n"
        "Bot đã kết nối thành công!\n"
        "🟢 POS · 🔴 NEG · ⚪ NEU"
    )
    print("OK" if ok else "FAILED")


asyncio.run(main())
