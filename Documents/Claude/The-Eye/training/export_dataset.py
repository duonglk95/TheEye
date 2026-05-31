"""
Phase 2 — Export dataset từ DB ra file để train PhoBERT.

Output: training/datasets/
  ├── train.csv       (80%)
  ├── val.csv         (10%)
  └── test.csv        (10%)

Columns: article_id, ticker, title, summary, content, label, category, labeler

Usage:
  python -m training.export_dataset [--labeler haiku-3-5] [--min-confidence 0.75]
"""
import asyncio
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
from sklearn.model_selection import train_test_split
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv; load_dotenv()

from app.db import AsyncSessionLocal
from app.db.models import ArticleMeta, ArticleContent, Company, TrainingLabel


DATASET_DIR = Path(__file__).parent / "datasets"
DATASET_DIR.mkdir(exist_ok=True)


async def fetch_labeled(labeler: str, min_confidence: float) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                ArticleMeta.id,
                ArticleMeta.title,
                ArticleMeta.summary,
                ArticleContent.content_raw,
                Company.ticker,
                TrainingLabel.label,
                TrainingLabel.category,
                TrainingLabel.labeler,
                TrainingLabel.confidence,
            )
            .join(Company,        ArticleMeta.company_id == Company.id)
            .join(TrainingLabel,  TrainingLabel.article_id == ArticleMeta.id)
            .outerjoin(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
            .where(TrainingLabel.labeler == labeler)
            .where(TrainingLabel.confidence >= min_confidence)
            .order_by(ArticleMeta.published_at.desc())
        )
        return [dict(r._mapping) for r in result.fetchall()]


def export(labeler: str, min_confidence: float):
    rows = asyncio.run(fetch_labeled(labeler, min_confidence))
    if not rows:
        print("Không có dữ liệu. Chạy label_with_claude.py trước.")
        return

    df = pd.DataFrame(rows)
    df["text"] = df["title"].fillna("") + " " + df["summary"].fillna("") + " " + df["content_raw"].fillna("")
    df["text"] = df["text"].str.strip()
    df = df[df["text"].str.len() > 20]  # lọc bài quá ngắn

    # Label distribution
    print(f"\nTổng: {len(df)} mẫu")
    print(df["label"].value_counts().to_string())
    print(f"\nTheo category:")
    print(df["category"].value_counts().to_string())

    # Split
    train_df, temp_df = train_test_split(df, test_size=0.2, random_state=42, stratify=df["label"])
    val_df, test_df  = train_test_split(temp_df, test_size=0.5, random_state=42, stratify=temp_df["label"])

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    for split_name, split_df in [("train", train_df), ("val", val_df), ("test", test_df)]:
        path = DATASET_DIR / f"{split_name}_{ts}.csv"
        split_df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  {split_name}: {len(split_df)} mẫu → {path}")

    print(f"\n✅ Dataset exported. Dùng file _latest để train:")
    print(f"   python -m training.train_phobert --train {DATASET_DIR}/train_{ts}.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--labeler",        default="haiku-3-5")
    parser.add_argument("--min-confidence", type=float, default=0.75)
    args = parser.parse_args()
    export(args.labeler, args.min_confidence)
