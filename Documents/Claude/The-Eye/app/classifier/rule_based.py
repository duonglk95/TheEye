"""
Rule-based reader — đọc rules từ sentiment.yaml, không cần GPU.

Hai cấp đọc:
  classify(title, summary)                 → chỉ tiêu đề + sapo (lúc vừa lấy RSS)
  read_article(title, summary, content)    → đọc cả thân bài, theo từng câu

Tại sao cần đọc thân bài: nhiều tin tốt/xấu không lộ ở tiêu đề.
VD "TTC AgriS nhận Huân chương Lao động" — tiêu đề trung tính về từ khoá,
nhưng thân bài toàn câu tích cực ("vinh dự", "ghi nhận đóng góp", "tăng trưởng"...).

Negation: nếu "không/chưa/khó..." xuất hiện trong 60 ký tự trước keyword
→ keyword bị huỷ (POS bị phủ định → tín hiệu NEG nhẹ 0.3).

Về con số % của rule-based:
  Luật KHÔNG có xác suất thật. Ta dùng ước lượng Laplace trên "lượng bằng chứng":
      p(nhãn) = (điểm_nhãn + 1) / (tổng_điểm + 3)
  → 1 từ khoá mạnh duy nhất cho ~50%, càng nhiều bằng chứng một chiều càng tiến về 100%,
  bằng chứng trái chiều kéo % xuống. Đây là ước lượng CHƯA HIỆU CHỈNH; khi đủ dữ liệu,
  mô hình ML (app/classifier/ml_model.py) thay thế và cho % đã hiệu chỉnh trên dữ liệu thật.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import load_sentiment

_SENTIMENT_PATH = Path(__file__).parent.parent.parent / "config" / "sentiment.yaml"
_cache: dict = {}
_cache_mtime: float = 0.0

# Trọng số theo vị trí trong bài: tiêu đề nói lên trọng tâm, thân bài nhiều câu
# nên mỗi câu nhẹ hơn và tổng thân bài bị chặn trên (tránh bài dài áp đảo).
TITLE_WEIGHT = 1.5
SAPO_WEIGHT = 1.2
BODY_SENTENCE_WEIGHT = 0.5
BODY_CAP = 4.0          # điểm thân bài tối đa mỗi chiều (sau khi nhân trọng số)
MAX_BODY_CHARS = 6000   # phần đầu bài là phần chính; cuối bài hay là "tin liên quan"


def _get_rules() -> dict:
    """Load rules, cache theo mtime để không đọc file mỗi lần classify."""
    global _cache, _cache_mtime
    mtime = _SENTIMENT_PATH.stat().st_mtime
    if mtime != _cache_mtime:
        _cache = load_sentiment()
        _cache_mtime = mtime
    return _cache


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _has_negation_before(text: str, keyword: str, negation_words: list[str], window: int = 60) -> bool:
    """True nếu MỌI lần xuất hiện của keyword đều có từ phủ định đứng trước trong `window` ký tự."""
    pos, found_any = 0, False
    while True:
        idx = text.find(keyword, pos)
        if idx == -1:
            break
        found_any = True
        context = text[max(0, idx - window):idx]
        if not any(neg in context and re.search(rf"(?<!\w){re.escape(neg)}(?!\w)", context)
                   for neg in negation_words):
            return False   # có ít nhất 1 lần xuất hiện không bị phủ định
        pos = idx + 1
    return found_any


@dataclass
class Evidence:
    pos: float = 0.0
    neg: float = 0.0
    neu_hit: bool = False
    hits: list[tuple[str, str, float]] = field(default_factory=list)  # (label, phrase, weight)

    def add(self, other: "Evidence", weight: float = 1.0) -> None:
        self.pos += other.pos * weight
        self.neg += other.neg * weight
        self.neu_hit = self.neu_hit or other.neu_hit
        self.hits.extend((lbl, p, w * weight) for lbl, p, w in other.hits)


_compiled: tuple[int, dict] | None = None


def _compile(rules: dict) -> dict:
    """Chuẩn hoá + biên dịch lexicon một lần cho mỗi phiên bản rules."""
    global _compiled
    if _compiled and _compiled[0] == id(rules):
        return _compiled[1]
    groups = []
    for label, section, kind, weight in (
        ("POS", "positive", "strong", 1.0), ("POS", "positive", "weak", 0.4),
        ("NEG", "negative", "strong", 1.0), ("NEG", "negative", "weak", 0.4),
    ):
        for kw in rules.get(section, {}).get(kind, []) or []:
            kw_norm = _normalize(kw)
            if kw_norm:
                groups.append((label, kw_norm, weight, re.compile(rf"(?<!\w){re.escape(kw_norm)}(?!\w)")))
    neu = [
        (k, re.compile(rf"(?<!\w){re.escape(k)}(?!\w)"))
        for k in (_normalize(x) for x in rules.get("neutral", {}).get("indicators", []) or []) if k
    ]
    neg_words = [_normalize(w) for w in rules.get("negation", {}).get("words", []) or [] if w]
    out = {"groups": groups, "neu": neu, "negation": neg_words}
    _compiled = (id(rules), out)
    return out


def score_text(text: str, rules: dict | None = None) -> Evidence:
    """Chấm điểm 1 đoạn text theo lexicon. Không quyết định nhãn."""
    lex = _compile(rules or _get_rules())
    text = _normalize(text)
    ev = Evidence()
    if not text:
        return ev

    for label, kw_norm, weight, pattern in lex["groups"]:
        # Lọc nhanh bằng substring (C) trước khi chạy regex ranh giới từ
        if kw_norm not in text or not pattern.search(text):
            continue
        if _has_negation_before(text, kw_norm, lex["negation"]):
            if label == "POS" and weight >= 1.0:
                ev.neg += 0.3          # "không đạt kế hoạch" → tín hiệu xấu nhẹ
                ev.hits.append(("NEG", f"không… {kw_norm}", 0.3))
            continue                   # "không vi phạm" → bỏ qua
        if label == "POS":
            ev.pos += weight
        else:
            ev.neg += weight
        ev.hits.append((label, kw_norm, weight))

    ev.neu_hit = any(k in text and p.search(text) for k, p in lex["neu"])
    return ev


def _decide(ev: Evidence, version: str) -> tuple[str, float, str]:
    """Từ bằng chứng → (nhãn, ước lượng Laplace, method)."""
    if ev.pos == 0 and ev.neg == 0:
        # Không có bằng chứng cảm xúc. Có chỉ báo trung tính → chắc hơn một chút.
        return "NEU", (0.7 if ev.neu_hit else 0.5), version

    total = ev.pos + ev.neg
    if abs(ev.pos - ev.neg) < 0.2:          # hoà / gần hoà → trung lập
        return "NEU", round(1 / 3 + 0.1, 3), version

    label = "POS" if ev.pos > ev.neg else "NEG"
    winner = max(ev.pos, ev.neg)
    score = (winner + 1) / (total + 3)
    return label, round(min(score, 0.95), 3), version


def classify(title: str, summary: str | None = None) -> tuple[str, float, str]:
    """
    Đọc nhanh tiêu đề + sapo.
    Returns: (label, score, method) — score là ước lượng chưa hiệu chỉnh (xem docstring module).
    """
    rules = _get_rules()
    ev = Evidence()
    ev.add(score_text(title, rules), TITLE_WEIGHT)
    ev.add(score_text(summary or "", rules), SAPO_WEIGHT)
    return _decide(ev, rules.get("version", "rule_v2"))


_SENT_SPLIT = re.compile(r"(?<=[.!?…;])\s+|\n+")


def split_sentences(content: str) -> list[str]:
    """Tách câu; bỏ dòng quá ngắn (menu, caption, "Xem thêm"...)."""
    parts = _SENT_SPLIT.split((content or "")[:MAX_BODY_CHARS])
    return [p.strip() for p in parts if len(p.strip()) >= 25]


@dataclass
class Reading:
    label: str
    score: float
    method: str
    evidence: Evidence
    body_sentences: int = 0
    body_pos_sentences: int = 0
    body_neg_sentences: int = 0


def read_article(title: str, summary: str | None, content: str | None) -> Reading:
    """
    Đọc cả bài: tiêu đề (×1.5), sapo (×1.2), từng câu thân bài (×0.5, chặn trên).
    Ghi lại tỷ lệ câu tích cực / tiêu cực trong thân bài.
    """
    rules = _get_rules()
    ev = Evidence()
    ev.add(score_text(title, rules), TITLE_WEIGHT)
    ev.add(score_text(summary or "", rules), SAPO_WEIGHT)

    sentences = split_sentences(content or "")
    body = Evidence()
    pos_s = neg_s = 0
    for s in sentences:
        s_ev = score_text(s, rules)
        if s_ev.pos > s_ev.neg:
            pos_s += 1
        elif s_ev.neg > s_ev.pos:
            neg_s += 1
        body.add(s_ev, BODY_SENTENCE_WEIGHT)

    if body.pos > BODY_CAP or body.neg > BODY_CAP:
        scale = BODY_CAP / max(body.pos, body.neg)
        body.pos *= scale
        body.neg *= scale
    ev.pos += body.pos
    ev.neg += body.neg
    ev.neu_hit = ev.neu_hit or body.neu_hit
    ev.hits.extend((lbl, p, w) for lbl, p, w in body.hits)

    label, score, method = _decide(ev, rules.get("version", "rule_v2"))
    return Reading(
        label=label, score=score, method=method + ("+full" if sentences else ""),
        evidence=ev, body_sentences=len(sentences),
        body_pos_sentences=pos_s, body_neg_sentences=neg_s,
    )


def top_phrases(ev: Evidence, label: str, k: int = 5) -> list[str]:
    """Các cụm từ khoá ủng hộ nhãn, gộp trùng, sắp theo tổng trọng số."""
    agg: dict[str, float] = {}
    for lbl, phrase, w in ev.hits:
        if lbl == label:
            agg[phrase] = agg.get(phrase, 0) + w
    return [p for p, _ in sorted(agg.items(), key=lambda x: -x[1])[:k]]
