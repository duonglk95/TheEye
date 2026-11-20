"""
Mô hình ML tự học — TF-IDF (n-gram âm tiết) + Logistic Regression + Temperature Scaling.

Vì sao chọn mô hình này (thay vì deep learning / LLM):
  - Chạy CPU, RAM ~100MB, train vài nghìn bài trong vài giây → hợp gói Railway rẻ nhất.
  - Tuyến tính → GIẢI THÍCH ĐƯỢC: mỗi cụm từ có trọng số, nên biết vì sao bot chấm POS/NEG.
  - Với vài trăm – vài nghìn bài có nhãn, TF-IDF + LR thường ngang các mô hình nặng hơn.
  - PhoBERT/torch cần ~1GB RAM + image ~2GB → chi phí Railway cao gấp nhiều lần.

Ý NGHĨA CỦA CON SỐ % (độ tin cậy):
  Logistic Regression cho ra xác suất, nhưng xác suất thô thường "tự tin quá mức".
  Ta hiệu chỉnh (calibrate) bằng Temperature Scaling: tìm 1 hệ số T trên tập kiểm định
  (bài mô hình chưa từng thấy khi train) sao cho xác suất khớp tần suất đúng thực tế.
  Sau hiệu chỉnh:  "bot nói 80%"  ≈  "trong 100 bài bot nói 80%, khoảng 80 bài đúng nhãn".
  Mức độ khớp được đo bằng ECE (Expected Calibration Error) và bảng reliability (POST /api/admin/train).

Module này thuần tính toán (không đụng DB) để dễ test.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

LABELS = ["NEG", "NEU", "POS"]
LABEL_IDX = {l: i for i, l in enumerate(LABELS)}

# Token đánh dấu bằng chứng từ lexicon luật → mô hình học được luật đáng tin tới đâu
_RULE_TOKENS = {"POS": "zzlexpos", "NEG": "zzlexneg"}
MAX_CONTENT_CHARS = 4000

# Hư từ không nên đứng đầu/cuối một cụm căn cứ
_EDGE_STOPWORDS = {
    "và", "của", "cho", "các", "những", "là", "đã", "được", "với", "trong", "tại", "này", "đó",
    "một", "có", "từ", "về", "theo", "để", "khi", "thì", "mà", "cũng", "sẽ", "đang", "vào", "ra",
}


def build_text(title: str, summary: str | None, content: str | None, rule_hits: dict | None = None) -> str:
    """
    Ghép văn bản đầu vào. Tiêu đề lặp 2 lần (trọng tâm bài), sau đó sapo, rồi thân bài.
    rule_hits: {"POS": n, "NEG": m} — số từ khoá luật khớp, thêm dưới dạng token đặc biệt.
    """
    parts = [title or "", title or "", summary or "", (content or "")[:MAX_CONTENT_CHARS]]
    text = " . ".join(p for p in parts if p)
    if rule_hits:
        extra = []
        for lbl, tok in _RULE_TOKENS.items():
            extra += [tok] * min(int(rule_hits.get(lbl, 0)), 5)
        text += " " + " ".join(extra)
    # Bỏ số thuần (giá, ngày tháng) — gây nhiễu, không mang cảm xúc
    return re.sub(r"\b\d[\d.,%]*\b", " ", text.lower())


@dataclass
class Sample:
    article_id: int
    text: str
    label: str
    weight: float = 1.0
    source: str = "silver"      # gold (người chấm) | llm (Claude chấm hộ) | silver (luật đọc toàn bài) | pseudo
    key: str = ""               # tiêu đề chuẩn hoá — gộp bài trùng (cùng tin đăng lại nhiều báo)
    group: str = ""             # ticker — cân bằng trọng số giữa các công ty
    dup_count: int = 1          # số bài trùng đã gộp vào mẫu này


def is_validation(article_id: int, ratio: int = 5) -> bool:
    """Chia tập cố định theo id (không ngẫu nhiên) → mỗi lần train dùng cùng tập kiểm định."""
    return (article_id * 2654435761) % 2**32 % ratio == 0


# ─── Calibration ────────────────────────────────────────────────

def softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_temperature(logits: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    """Tìm T > 0 cực tiểu hoá negative log-likelihood (có trọng số) trên tập kiểm định."""
    w = np.ones(len(y)) if w is None else w
    best_t, best_nll = 1.0, math.inf
    for t in np.logspace(-1.3, 1.3, 260):     # T ∈ [0.05, 20]
        p = softmax(logits / t)
        nll = -np.sum(w * np.log(p[np.arange(len(y)), y] + 1e-12)) / w.sum()
        if nll < best_nll:
            best_t, best_nll = float(t), nll
    return best_t


RELIABILITY_BINS = [(0.33, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0001)]


def calibration_report(probs: np.ndarray, y: np.ndarray) -> dict:
    """
    ECE + bảng reliability: với mỗi khoảng độ tin cậy, bot nói bao nhiêu % và thực tế đúng bao nhiêu %.
    """
    conf = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    correct = (pred == y).astype(float)
    n = len(y)
    ece, bins = 0.0, []
    for lo, hi in RELIABILITY_BINS:
        m = (conf >= lo) & (conf < hi)
        if not m.any():
            continue
        avg_conf, acc = float(conf[m].mean()), float(correct[m].mean())
        ece += m.sum() / n * abs(avg_conf - acc)
        bins.append({"range": f"{int(lo*100)}–{min(int(hi*100), 100)}%", "n": int(m.sum()),
                     "said": round(avg_conf, 3), "actual": round(acc, 3)})
    return {"ece": round(ece, 4), "bins": bins}


def classification_metrics(pred: np.ndarray, y: np.ndarray) -> dict:
    """Accuracy + macro-F1 + precision/recall từng nhãn."""
    out = {"n": int(len(y)), "accuracy": round(float((pred == y).mean()), 4) if len(y) else 0.0, "per_label": {}}
    f1s = []
    for i, lbl in enumerate(LABELS):
        tp = int(((pred == i) & (y == i)).sum())
        fp = int(((pred == i) & (y != i)).sum())
        fn = int(((pred != i) & (y == i)).sum())
        if tp + fn == 0:
            continue                    # nhãn không có trong tập → không tính vào macro
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f1)
        out["per_label"][lbl] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": tp + fn}
    out["macro_f1"] = round(float(np.mean(f1s)), 4) if f1s else 0.0
    return out


# ─── Model bundle ───────────────────────────────────────────────

@dataclass
class ModelBundle:
    version: int
    vectorizer: object
    clf: object
    temperature: float
    trained_at: str
    metrics: dict = field(default_factory=dict)

    def logits(self, texts: list[str]) -> np.ndarray:
        """Logit theo thứ tự LABELS (đủ 3 cột kể cả khi lúc train thiếu 1 nhãn)."""
        return _full_logits(self, self.vectorizer.transform(texts))

    def predict_proba(self, texts: list[str]) -> np.ndarray:
        return softmax(self.logits(texts) / self.temperature)

    def explain(self, text: str, label: str, k: int = 4) -> list[str]:
        """
        Các cụm từ trong bài đẩy mạnh nhất về phía `label` (đóng góp = tf-idf × hệ số).
        Các n-gram chồng lên nhau / liền kề được ghép lại thành cụm đọc được
        (VD "ghi nhận đóng" + "đóng góp cho" → "ghi nhận đóng góp").
        """
        classes = list(self.clf.classes_)
        if LABEL_IDX[label] not in classes:
            return []
        coef = self.clf.coef_
        if coef.shape[0] == 1:          # mô hình 2 lớp: coef_ là hướng của lớp thứ 2
            rel = coef[0] if classes.index(LABEL_IDX[label]) == 1 else -coef[0]
        else:
            c = classes.index(LABEL_IDX[label])
            rel = coef[c] - coef.mean(axis=0)

        row = self.vectorizer.transform([text]).tocoo()
        names = self.vectorizer.get_feature_names_out()
        contrib = sorted(
            ((float(v * rel[j]), names[j]) for j, v in zip(row.col, row.data)
             if v * rel[j] > 0 and not names[j].startswith("zzlex")),
            reverse=True,
        )[:12]
        if not contrib:
            return []

        # Vị trí của từng n-gram trong chuỗi token → gộp các khoảng chồng/kề nhau
        tokens = re.findall(r"(?u)\b\w+\b", text)
        spans: list[list] = []            # [start, end, score]
        for score, name in contrib:
            words = name.split()
            for i in range(len(tokens) - len(words) + 1):
                if tokens[i:i + len(words)] == words:
                    spans.append([i, i + len(words), score])
                    break
        spans.sort()
        merged: list[list] = []
        for sp in spans:
            if merged and sp[0] <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], sp[1])
                merged[-1][2] += sp[2]
            else:
                merged.append(sp)

        out: list[str] = []
        for start, end, _ in sorted(merged, key=lambda m: -m[2]):
            words = tokens[start:end]
            while words and words[0] in _EDGE_STOPWORDS:
                words = words[1:]
            while words and words[-1] in _EDGE_STOPWORDS:
                words = words[:-1]
            phrase = " ".join(words)
            if phrase and phrase not in out and len(phrase) >= 3:
                out.append(phrase)
            if len(out) >= k:
                break
        return out

    def to_bytes(self) -> bytes:
        import joblib
        buf = io.BytesIO()
        joblib.dump(self, buf, compress=3)
        return buf.getvalue()

    @staticmethod
    def from_bytes(blob: bytes) -> "ModelBundle":
        import joblib
        return joblib.load(io.BytesIO(blob))


MIN_TRAIN = 40
MIN_PER_CLASS = 5
MIN_VAL = 15


def train(samples: list[Sample], version: int, c_grid=(0.5, 2.0, 8.0)) -> tuple[ModelBundle | None, dict]:
    """
    Train + hiệu chỉnh + đánh giá. Trả về (bundle | None, report).
    bundle=None khi chưa đủ dữ liệu (report["reason"] giải thích).
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    tr = [s for s in samples if not is_validation(s.article_id)]
    va = [s for s in samples if is_validation(s.article_id)]
    counts = {l: sum(1 for s in tr if s.label == l) for l in LABELS}
    report = {"n_train": len(tr), "n_val": len(va), "train_counts": counts,
              "sources": {src: sum(1 for s in samples if s.source == src) for src in ("gold", "llm", "silver", "pseudo")}}

    if len(tr) < MIN_TRAIN or len(va) < MIN_VAL or sum(1 for v in counts.values() if v >= MIN_PER_CLASS) < 2:
        report["reason"] = (f"Chưa đủ dữ liệu: cần ≥{MIN_TRAIN} bài train, ≥{MIN_VAL} bài kiểm định, "
                            f"≥2 nhãn có ≥{MIN_PER_CLASS} bài (hiện {len(tr)} / {len(va)} / {counts})")
        return None, report

    vec = TfidfVectorizer(
        token_pattern=r"(?u)\b\w+\b", ngram_range=(1, 3), min_df=2, max_df=0.9,
        sublinear_tf=True, max_features=60000,
    )
    Xtr = vec.fit_transform([s.text for s in tr])
    ytr = np.array([LABEL_IDX[s.label] for s in tr])
    wtr = np.array([s.weight for s in tr])
    Xva = vec.transform([s.text for s in va])
    yva = np.array([LABEL_IDX[s.label] for s in va])
    wva = np.array([s.weight for s in va])

    best = None
    for C in c_grid:
        clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
        clf.fit(Xtr, ytr, sample_weight=wtr)
        f1 = classification_metrics(clf.predict(Xva), yva)["macro_f1"]
        if best is None or f1 > best[0]:
            best = (f1, C, clf)
    _, C, clf = best

    bundle = ModelBundle(version=version, vectorizer=vec, clf=clf, temperature=1.0,
                         trained_at=datetime.now(timezone.utc).isoformat())
    # Điền 3 cột kể cả khi train thiếu 1 nhãn
    raw = _full_logits(bundle, Xva)
    bundle.temperature = fit_temperature(raw, yva, wva)
    probs = softmax(raw / bundle.temperature)

    report.update(evaluate(probs, yva, [s.source for s in va]))
    report["C"] = C
    report["temperature"] = round(bundle.temperature, 3)
    bundle.metrics = report
    return bundle, report


def _full_logits(bundle: ModelBundle, X) -> np.ndarray:
    z = bundle.clf.decision_function(X)
    if z.ndim == 1:                      # chỉ 2 lớp → decision_function 1 chiều
        z = np.stack([-z / 2, z / 2], axis=1)
    out = np.full((X.shape[0], len(LABELS)), -1e3)
    for col, cls in enumerate(bundle.clf.classes_):
        out[:, cls] = z[:, col]
    return out


def evaluate(probs: np.ndarray, y: np.ndarray, sources: list[str]) -> dict:
    """Đánh giá trên toàn tập kiểm định và riêng phần nhãn người dùng (gold)."""
    pred = probs.argmax(axis=1)
    out = {"val": {**classification_metrics(pred, y), **calibration_report(probs, y)}}
    gold = np.array([s == "gold" for s in sources])
    if gold.sum() >= 10:
        out["val_gold"] = {**classification_metrics(pred[gold], y[gold]), **calibration_report(probs[gold], y[gold])}
    return out


def headline_score(report: dict) -> float:
    """Điểm để so model mới vs cũ: ưu tiên macro-F1 trên nhãn người dùng nếu có."""
    if "val_gold" in report:
        return report["val_gold"]["macro_f1"]
    return report.get("val", {}).get("macro_f1", 0.0)
