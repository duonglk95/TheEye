"""
Config loader — đọc YAML files.
Các module khác import từ đây, không import yaml trực tiếp.
"""
from functools import lru_cache
from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_companies() -> list[dict]:
    data = yaml.safe_load((CONFIG_DIR / "companies.yaml").read_text())
    return data.get("companies", [])


def load_sources() -> list[dict]:
    data = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    return data.get("feeds", [])


def load_sentiment() -> dict:
    """Load sentiment config — không cache vì cần reload sau khi update model_path."""
    return yaml.safe_load((CONFIG_DIR / "sentiment.yaml").read_text())
