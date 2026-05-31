"""
Test bot commands offline — không cần Telegram, chỉ test report builder.
Usage: python scripts/test_bot.py [TICKER] [hours]

Ví dụ:
  python scripts/test_bot.py VIC
  python scripts/test_bot.py SBT 48h
  python scripts/test_bot.py --all
  python scripts/test_bot.py --top neg 7d
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()


async def main():
    args = sys.argv[1:]

    if not args or args[0] == "--help":
        print(__doc__)
        return

    from app.notifier.report_builder import (
        build_company_report,
        build_overview_report,
        build_top_report,
    )
    # Strip HTML tags để hiển thị trên terminal
    import re
    def strip_html(text):
        return re.sub(r"<[^>]+>", "", text)

    if args[0] == "--all":
        hours = int(args[1].replace("h","").replace("d","")) * (24 if "d" in (args[1] if len(args)>1 else "") else 1) if len(args) > 1 else 24
        text = await build_overview_report(hours)
    elif args[0] == "--top":
        sentiment = args[1].upper() if len(args) > 1 else "NEG"
        hours_raw = args[2] if len(args) > 2 else "24h"
        hours = int(hours_raw.replace("h","").replace("d","")) * (24 if "d" in hours_raw else 1)
        text = await build_top_report(sentiment, hours)
    else:
        ticker = args[0]
        hours_raw = args[1] if len(args) > 1 else "24h"
        hours = int(hours_raw.replace("h","").replace("d","")) * (24 if "d" in hours_raw else 1)
        text = await build_company_report(ticker, hours)

    print(strip_html(text))


asyncio.run(main())
