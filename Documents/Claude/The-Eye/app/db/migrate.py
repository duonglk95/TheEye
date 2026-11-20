"""
Áp dụng toàn bộ file migrations/*.sql theo thứ tự tên (idempotent — dùng IF NOT EXISTS).
Gọi lúc khởi động service để deploy Railway không cần chạy tay.
"""
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def apply_migrations() -> list[str]:
    import asyncpg

    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    applied = []
    try:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            await conn.execute(path.read_text(encoding="utf-8"))
            applied.append(path.name)
    finally:
        await conn.close()
    log.info(f"Migrations applied: {', '.join(applied)}")
    return applied
