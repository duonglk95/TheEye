"""
Seed companies và feed_sources từ YAML config vào DB.
Chạy một lần khi setup hoặc khi thêm company/source mới.

Usage: python -m app.db.seed
"""
import asyncio
import os
import yaml
from pathlib import Path
from sqlalchemy import select
from app.db import AsyncSessionLocal
from app.db.models import Company, FeedSource

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


async def seed_companies(session):
    data = yaml.safe_load((CONFIG_DIR / "companies.yaml").read_text())
    for c in data["companies"]:
        existing = await session.scalar(
            select(Company).where(Company.ticker == c["ticker"])
        )
        if existing:
            existing.name = c["name"]
            existing.full_name = c.get("full_name")
            existing.aliases = c.get("aliases", [])
            existing.keywords = c.get("keywords", [])
            existing.sector = c.get("sector")
            existing.exchange = c.get("exchange")
            existing.active = c.get("active", True)
            print(f"  updated: {c['ticker']}")
        else:
            session.add(Company(
                ticker=c["ticker"],
                name=c["name"],
                full_name=c.get("full_name"),
                aliases=c.get("aliases", []),
                keywords=c.get("keywords", []),
                sector=c.get("sector"),
                exchange=c.get("exchange"),
                active=c.get("active", True),
            ))
            print(f"  inserted: {c['ticker']}")


async def seed_sources(session):
    data = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    defaults = data.get("defaults", {})

    for f in data["feeds"]:
        if f.get("type") == "google_rss":
            # Template feed — skip, được tạo dynamically lúc runtime
            continue

        poll_interval = f.get(
            "poll_interval_sec", defaults.get("poll_interval_sec", 300)
        )
        existing = await session.scalar(
            select(FeedSource).where(FeedSource.source_id == f["id"])
        )
        if existing:
            existing.name = f["name"]
            existing.url = f["url"]
            existing.type = f.get("type", "rss")
            existing.priority = f.get("priority", "medium")
            existing.poll_interval_sec = poll_interval
            existing.active = f.get("active", True)
            print(f"  updated: {f['id']}")
        else:
            session.add(FeedSource(
                source_id=f["id"],
                name=f["name"],
                url=f["url"],
                type=f.get("type", "rss"),
                priority=f.get("priority", "medium"),
                poll_interval_sec=poll_interval,
                active=f.get("active", True),
            ))
            print(f"  inserted: {f['id']}")


async def main():
    async with AsyncSessionLocal() as session:
        print("Seeding companies...")
        await seed_companies(session)
        print("Seeding feed sources...")
        await seed_sources(session)
        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
