"""
Chạy DB migration + seed.
Usage: python scripts/run_seed.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()


async def main():
    from app.db.migrate import apply_migrations

    applied = await apply_migrations()
    print(f"Migrations applied: {', '.join(applied)}")

    from app.db.seed import main as seed_main
    await seed_main()


asyncio.run(main())
