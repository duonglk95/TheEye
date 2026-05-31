"""
Phase 2 — Fine-tune PhoBERT cho sentiment classification.
Chạy local (GPU) hoặc Colab.

Usage:
  python -m training.train_phobert \
    --train datasets/train_YYYYMMDD.csv \
    --val   datasets/val_YYYYMMDD.csv   \
    --output models/phobert_v1          \
    --epochs 5 --batch-size 16

Sau khi train xong → chạy update_config.py để cập nhật sentiment.yaml.
"""
import argparse
import os
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    AdamW,
    get_linear_schedule_with_warmup,
)
from sklearn.metrics import classification_report, confusion_matrix

LABEL2ID = {"NEU": 0, "POS": 1, "NEG": 2}
ID2LABEL = {v: k for k, v in LABEL2ID.items()}
MODEL_NAME = "vinai/phobert-base-v2"


class NewsDataset(Dataset):
    def __init__(self, df: pd.DataFrame, tokenizer, max_len: int = 256):
        self.texts  = df["text"].tolist()
        self.labels = df["label"].map(LABEL2ID).tolist()
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        enc = self.tokenizer(
            self.texts[idx],
            max_length=self.max_len,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        return {
            "input_ids":      enc["input_ids"].squeeze(),
            "attention_mask": enc["attention_mask"].squeeze(),
            "label":          torch.tensor(self.labels[idx], dtype=torch.long),
        }


def train(args):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    ).to(device)

    train_df = pd.read_csv(args.train)
    val_df   = pd.read_csv(args.val)
    print(f"Train: {len(train_df)} | Val: {len(val_df)}")

    train_loader = DataLoader(
        NewsDataset(train_df, tokenizer, args.max_len),
        batch_size=args.batch_size, shuffle=True
    )
    val_loader = DataLoader(
        NewsDataset(val_df, tokenizer, args.max_len),
        batch_size=args.batch_size * 2
    )

    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=total_steps // 10, num_training_steps=total_steps
    )

    best_val_f1 = 0.0
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, args.epochs + 1):
        # ── Train ──
        model.train()
        total_loss = 0
        for batch in train_loader:
            optimizer.zero_grad()
            out = model(
                input_ids=batch["input_ids"].to(device),
                attention_mask=batch["attention_mask"].to(device),
                labels=batch["label"].to(device),
            )
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            total_loss += out.loss.item()

        avg_loss = total_loss / len(train_loader)

        # ── Eval ──
        model.eval()
        all_preds, all_labels = [], []
        with torch.no_grad():
            for batch in val_loader:
                logits = model(
                    input_ids=batch["input_ids"].to(device),
                    attention_mask=batch["attention_mask"].to(device),
                ).logits
                preds = logits.argmax(dim=-1).cpu().numpy()
                all_preds.extend(preds)
                all_labels.extend(batch["label"].numpy())

        report = classification_report(
            all_labels, all_preds,
            target_names=["NEU", "POS", "NEG"],
            output_dict=True,
        )
        val_f1 = report["macro avg"]["f1-score"]

        print(
            f"Epoch {epoch}/{args.epochs} | loss={avg_loss:.4f} | "
            f"val_f1={val_f1:.4f} | "
            f"POS={report['POS']['f1-score']:.3f} "
            f"NEG={report['NEG']['f1-score']:.3f} "
            f"NEU={report['NEU']['f1-score']:.3f}"
        )

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            model.save_pretrained(str(output_dir))
            tokenizer.save_pretrained(str(output_dir))
            print(f"  ✅ Best model saved → {output_dir}")

    # Save metadata
    meta = {
        "model_path": str(output_dir),
        "base_model": MODEL_NAME,
        "best_val_f1": best_val_f1,
        "label2id": LABEL2ID,
        "train_samples": len(train_df),
        "val_samples": len(val_df),
        "trained_at": datetime.now().isoformat(),
        "args": vars(args),
    }
    (output_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"\n🎯 Training done! Best F1: {best_val_f1:.4f}")
    print(f"   → Cập nhật config: python -m training.update_config --model {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train",      required=True)
    parser.add_argument("--val",        required=True)
    parser.add_argument("--output",     default="models/phobert_v1")
    parser.add_argument("--epochs",     type=int,   default=5)
    parser.add_argument("--batch-size", type=int,   default=16)
    parser.add_argument("--lr",         type=float, default=2e-5)
    parser.add_argument("--max-len",    type=int,   default=256)
    train(parser.parse_args())
