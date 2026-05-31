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
    import asyncpg
    from pathlib import Path

    db_url = os.environ["DATABASE_URL"]
    # asyncpg dùng DSN trực tiếp
    conn = await asyncpg.connect(db_url)
    sql = (Path(__file__).parent.parent / "app/db/migrations/001_init.sql").read_text()
    await conn.execute(sql)
    await conn.close()
    print("Migration applied.")

    from app.db.seed import main as seed_main
    await seed_main()


asyncio.run(main())
