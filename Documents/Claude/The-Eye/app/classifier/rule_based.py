"""
Rule-based classifier — đọc rules từ sentiment.yaml, không cần GPU.
Trả về (label, score, method).
"""
import re
from app.config import load_sentiment

_cache: dict = {}
_cache_mtime: float = 0.0


def _get_rules() -> dict:
    """Load rules, cache để không đọc file mỗi lần classify."""
    import time
    from pathlib import Path
    path = Path(__file__).parent.parent.parent / "config" / "sentiment.yaml"
    mtime = path.stat().st_mtime
    global _cache, _cache_mtime
    if mtime != _cache_mtime:
        _cache = load_sentiment()
        _cache_mtime = mtime
    return _cache


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def classify(title: str, summary: str | None = None) -> tuple[str, float, str]:
    """
    Classify text theo rules.
    Returns: (label, confidence_score, method_name)
      label: NEU | POS | NEG
      score: 0.0 – 1.0
    """
    rules = _get_rules()
    version = rules.get("version", "rule_v1")
    text = _normalize(f"{title} {summary or ''}")

    pos_strong = rules.get("positive", {}).get("strong", [])
    pos_weak   = rules.get("positive", {}).get("weak", [])
    neg_strong = rules.get("negative", {}).get("strong", [])
    neg_weak   = rules.get("negative", {}).get("weak", [])
    neu_ind    = rules.get("neutral", {}).get("indicators", [])

    pos_score = 0.0
    neg_score = 0.0

    for kw in pos_strong:
        if _normalize(kw) in text:
            pos_score += 1.0

    for kw in pos_weak:
        if _normalize(kw) in text:
            pos_score += 0.4

    for kw in neg_strong:
        if _normalize(kw) in text:
            neg_score += 1.0

    for kw in neg_weak:
        if _normalize(kw) in text:
            neg_score += 0.4

    # NEU override: nếu chỉ toàn neutral indicator → NEU
    neu_hit = any(_normalize(kw) in text for kw in neu_ind)

    if pos_score == 0 and neg_score == 0:
        return "NEU", 1.0 if neu_hit else 0.6, version

    total = pos_score + neg_score

    if neg_score > pos_score:
        score = min(neg_score / (total + 0.001), 0.95)
        return "NEG", round(score, 3), version

    if pos_score > neg_score:
        score = min(pos_score / (total + 0.001), 0.95)
        return "POS", round(score, 3), version

    # Tie → NEU
    return "NEU", 0.5, version
