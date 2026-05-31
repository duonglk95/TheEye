"""
Rule-based classifier — đọc rules từ sentiment.yaml, không cần GPU.
Trả về (label, score, method).

Negation: nếu "không/chưa/khó..." xuất hiện trong 60 ký tự trước keyword POS
→ điểm POS bị huỷ, thay bằng tín hiệu NEG nhẹ (0.3).
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


def _has_negation_before(text: str, keyword: str, negation_words: list[str], window: int = 60) -> bool:
    """Trả về True nếu có từ phủ định trong `window` ký tự trước keyword."""
    pos = 0
    while True:
        idx = text.find(keyword, pos)
        if idx == -1:
            break
        context = text[max(0, idx - window):idx]
        if any(neg in context for neg in negation_words):
            return True
        pos = idx + 1
    return False


def classify(title: str, summary: str | None = None) -> tuple[str, float, str]:
    """
    Classify text theo rules.
    Returns: (label, confidence_score, method_name)
      label: NEU | POS | NEG
      score: 0.0 – 1.0
    """
    rules = _get_rules()
    version = rules.get("version", "rule_v2")
    text = _normalize(f"{title} {summary or ''}")

    pos_strong = rules.get("positive", {}).get("strong", [])
    pos_weak   = rules.get("positive", {}).get("weak", [])
    neg_strong = rules.get("negative", {}).get("strong", [])
    neg_weak   = rules.get("negative", {}).get("weak", [])
    neu_ind    = rules.get("neutral", {}).get("indicators", [])
    neg_words  = rules.get("negation", {}).get("words", [])

    pos_score = 0.0
    neg_score = 0.0

    for kw in pos_strong:
        kw_norm = _normalize(kw)
        if kw_norm in text:
            if _has_negation_before(text, kw_norm, neg_words):
                neg_score += 0.3  # phủ định positive → tín hiệu tiêu cực nhẹ
            else:
                pos_score += 1.0

    for kw in pos_weak:
        kw_norm = _normalize(kw)
        if kw_norm in text:
            if _has_negation_before(text, kw_norm, neg_words):
                pass  # phủ định weak positive → bỏ qua
            else:
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
