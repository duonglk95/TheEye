"""
Phase 2 — Cập nhật sentiment.yaml với model PhoBERT mới.
Chạy sau khi train_phobert.py xong.

Usage:
  python -m training.update_config --model models/phobert_v1
"""
import argparse
import json
import sys
import os
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sentiment.yaml"


def update(model_path: str):
    model_dir = Path(model_path)
    meta_path = model_dir / "meta.json"

    if not model_dir.exists():
        print(f"❌ Model dir không tồn tại: {model_dir}")
        return

    # Đọc metadata train
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        print(f"Model: {model_dir.name}")
        print(f"  Base: {meta.get('base_model')}")
        print(f"  Val F1: {meta.get('best_val_f1', 0):.4f}")
        print(f"  Trained at: {meta.get('trained_at')}")

    # Đọc config hiện tại
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    old_path = cfg.get("model_path")
    old_version = cfg.get("version")

    # Tăng version
    version_parts = old_version.split("_")
    if version_parts[0] in ("rule", "phobert"):
        try:
            v_num = int(version_parts[-1].replace("v", ""))
            new_version = f"phobert_v{v_num + 1}"
        except ValueError:
            new_version = "phobert_v1"
    else:
        new_version = "phobert_v1"

    # Update
    cfg["version"] = new_version
    cfg["model_path"] = str(model_dir.absolute())
    cfg["updated_at"] = __import__("datetime").date.today().isoformat()

    CONFIG_PATH.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False))

    print(f"\n✅ sentiment.yaml updated:")
    print(f"   version:    {old_version} → {new_version}")
    print(f"   model_path: {old_path or 'null'} → {cfg['model_path']}")
    print(f"\n⚡ Service sẽ tự load model mới trong lần classify tiếp theo (không cần restart).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Đường dẫn thư mục model")
    args = parser.parse_args()
    update(args.model)
