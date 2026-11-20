"""
Vòng tự học — chạy mỗi đêm (02:30) hoặc qua POST /api/admin/train (admin).

  1. GOM DỮ LIỆU
     gold   : nhãn người dùng xác nhận qua Telegram            trọng số 3.0
     silver : luật đọc TOÀN BÀI cho kết quả rõ ràng            trọng số 1.0
              (bằng chứng một chiều đủ mạnh, ở cả thân bài)
     pseudo : bài mô hình hiện tại tự tin ≥ 90% (self-training) trọng số 0.5
              — chỉ bật khi mô hình hiện tại đã được kiểm chứng trên ≥30 nhãn người dùng
                và hiệu chỉnh tốt (ECE ≤ 0.08), để tránh "tự học cái sai của chính mình".

  2. TRAIN mô hình mới (TF-IDF + Logistic Regression), hiệu chỉnh % bằng Temperature Scaling.

  3. CỔNG KIỂM ĐỊNH: so mô hình mới với mô hình đang chạy trên CÙNG tập kiểm định
     (ưu tiên nhãn người dùng). Chỉ thay khi mới ≥ cũ. Ngược lại giữ mô hình cũ, lưu lý do.

Mô hình học được cụm từ mà luật không có: VD bài "Huân chương Lao động" được người
dùng đánh dấu 🟢 → các cụm "huân chương", "vinh dự", "ghi nhận đóng góp" có trọng số
dương → lần sau tin tương tự được nhận ra dù tiêu đề không có từ khoá luật.
"""
import asyncio
import logging
import re
from collections import Counter, defaultdict

import numpy as np
from sqlalchemy import func, select

from app.classifier import model_store
from app.classifier import ml_model
from app.classifier.ml_model import LABEL_IDX, LABELS, Sample, build_text
from app.classifier.rule_based import read_article
from app.db import AsyncSessionLocal
from app.db.models import ArticleContent, ArticleMeta, Company, TrainingLabel
from app.learning.feedback import HUMAN_PREFIX
from app.learning.label_export import LLM_PREFIX

log = logging.getLogger(__name__)

GOLD_WEIGHT = 3.0             # nhãn chắc chắn (😡/🤩, nút cũ, /fix)
GOLD_MILD_WEIGHT = 2.0        # mức nhẹ (rating 2/4) nếu sau này có
LLM_WEIGHT = 1.5              # nhãn Claude chấm hộ qua Scheduled Task: tin hơn luật, kém người chấm
SILVER_WEIGHT = 1.0
PSEUDO_WEIGHT = 0.5
SILVER_MIN_MARGIN = 1.5        # chênh lệch điểm POS-NEG tối thiểu để tin luật
PSEUDO_MIN_PROB = 0.90
PSEUDO_GATE_GOLD = 30
PSEUDO_GATE_ECE = 0.08
MAX_ARTICLES = 6000           # giới hạn RAM: ~6000 bài × 6KB nội dung


def _rule_hits(reading) -> dict:
    return {
        "POS": sum(1 for l, _, _ in reading.evidence.hits if l == "POS"),
        "NEG": sum(1 for l, _, _ in reading.evidence.hits if l == "NEG"),
    }


def silver_label(reading) -> str | None:
    """
    Nhãn bạc từ luật — chỉ khi chắc chắn:
      POS/NEG: chênh lệch ≥ 1.5 và thân bài không nghiêng về phía ngược lại
      NEU    : có chỉ báo trung tính, không có bất kỳ tín hiệu cảm xúc nào trong cả bài
    Bài chưa có thân bài → không dùng làm nhãn bạc (quá ít thông tin).
    """
    if reading.body_sentences == 0:
        return None
    ev = reading.evidence
    margin = ev.pos - ev.neg
    if margin >= SILVER_MIN_MARGIN and reading.body_neg_sentences <= reading.body_pos_sentences:
        return "POS"
    if -margin >= SILVER_MIN_MARGIN and reading.body_pos_sentences <= reading.body_neg_sentences:
        return "NEG"
    if ev.pos == 0 and ev.neg == 0 and ev.neu_hit:
        return "NEU"
    return None


def _vote_weight(rating: int | None) -> float:
    return GOLD_WEIGHT if rating in (None, 1, 5) else GOLD_MILD_WEIGHT


def _gold_by_article(rows) -> dict[int, tuple[str, float]]:
    """
    Nhiều người cùng chấm 1 bài → lấy đa số; hoà thì lấy nhãn mới nhất.
    Trọng số = trung bình độ chắc của các phiếu cùng nhãn thắng (😡/🤩 nặng hơn 🙁/🙂).
    rows: (article_id, label, created_at, rating)
    """
    votes: dict[int, list[tuple]] = defaultdict(list)
    for article_id, label, created_at, rating in rows:
        votes[article_id].append((label, created_at, rating))
    out = {}
    for aid, vs in votes.items():
        counts = Counter(v[0] for v in vs)
        top = max(counts.values())
        tied = {l for l, c in counts.items() if c == top}
        label = max((v for v in vs if v[0] in tied), key=lambda v: v[1] or 0)[0]
        weights = [_vote_weight(v[2]) for v in vs if v[0] == label]
        out[aid] = (label, sum(weights) / len(weights))
    return out


async def build_dataset(current: ml_model.ModelBundle | None) -> tuple[list[Sample], dict]:
    async with AsyncSessionLocal() as session:
        gold_rows = await session.execute(
            select(TrainingLabel.article_id, TrainingLabel.label, TrainingLabel.created_at, TrainingLabel.rating)
            .where(TrainingLabel.labeler.like(f"{HUMAN_PREFIX}%"))
        )
        gold = _gold_by_article(gold_rows.all())

        llm_rows = await session.execute(
            select(TrainingLabel.article_id, TrainingLabel.label, TrainingLabel.created_at)
            .where(TrainingLabel.labeler.like(f"{LLM_PREFIX}%"))
            .order_by(TrainingLabel.created_at)
        )
        llm = {aid: label for aid, label, _ in llm_rows.all()}     # mới nhất ghi đè

        cols = (ArticleMeta.id, ArticleMeta.title, ArticleMeta.summary, func.left(ArticleContent.content_raw, 6000),
                Company.ticker)
        recent = await session.execute(
            select(*cols)
            .outerjoin(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
            .outerjoin(Company, Company.id == ArticleMeta.company_id)
            .order_by(ArticleMeta.id.desc())
            .limit(MAX_ARTICLES)
        )
        articles = recent.all()
        # Bài có nhãn (người / LLM) nhưng cũ hơn cửa sổ gần đây → vẫn đưa vào
        seen = {a[0] for a in articles}
        missing = [aid for aid in set(gold) | set(llm) if aid not in seen]
        if missing:
            older = await session.execute(
                select(*cols)
                .outerjoin(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
                .outerjoin(Company, Company.id == ArticleMeta.company_id)
                .where(ArticleMeta.id.in_(missing))
            )
            articles += older.all()

    pseudo_on = bool(
        current is not None
        and current.metrics.get("val_gold", {}).get("n", 0) >= PSEUDO_GATE_GOLD
        and current.metrics.get("val_gold", {}).get("ece", 1.0) <= PSEUDO_GATE_ECE
    )

    samples: list[Sample] = []
    pseudo_candidates: list[tuple[int, str, str, str]] = []
    for aid, title, summary, content, ticker in articles:
        reading = read_article(title, summary, content)
        text = build_text(title, summary, content, _rule_hits(reading))
        key, group = title_key(title), ticker or "_none"
        if aid in gold:
            label, weight = gold[aid]
            samples.append(Sample(aid, text, label, weight, "gold", key, group))
            continue
        if aid in llm:
            samples.append(Sample(aid, text, llm[aid], LLM_WEIGHT, "llm", key, group))
            continue
        lbl = silver_label(reading)
        if lbl:
            samples.append(Sample(aid, text, lbl, SILVER_WEIGHT, "silver", key, group))
        elif pseudo_on and content:
            pseudo_candidates.append((aid, text, key, group))

    # Self-training: chỉ lấy pseudo vào tập TRAIN, không bao giờ vào tập kiểm định
    if pseudo_candidates:
        texts = [c[1] for c in pseudo_candidates]
        probs = current.predict_proba(texts)
        cap = max(10, len(samples) // 2)       # pseudo không quá 1/2 dữ liệu thật
        picked = [
            (aid, text, key, group, LABELS[int(p.argmax())], float(p.max()))
            for (aid, text, key, group), p in zip(pseudo_candidates, probs)
            if p.max() >= PSEUDO_MIN_PROB and not ml_model.is_validation(aid)
        ]
        picked.sort(key=lambda x: -x[5])
        samples += [Sample(aid, text, lbl, PSEUDO_WEIGHT, "pseudo", key, group)
                    for aid, text, key, group, lbl, _ in picked[:cap]]

    samples, balance = dedupe_and_balance(samples)
    info = {"articles_scanned": len(articles), "gold": len(gold), "llm": len(llm),
            "pseudo_enabled": pseudo_on, "dedup_balance": balance}
    return samples, info


# ─── Gộp bài trùng & cân bằng công ty ───────────────────────────

SOURCE_RANK = {"gold": 3, "llm": 2, "silver": 1, "pseudo": 0}
BALANCE_MIN, BALANCE_MAX = 0.33, 3.0


def title_key(title: str) -> str:
    """Tiêu đề chuẩn hoá để nhận ra cùng 1 tin đăng lại: bỏ đuôi tên báo, dấu câu, khoảng trắng thừa."""
    from app.notifier.formatting import short_title
    t = short_title(title or "", limit=10_000, strip_source=True).lower()
    return re.sub(r"\W+", " ", t).strip()


def dedupe_and_balance(samples: list[Sample]) -> tuple[list[Sample], dict]:
    """
    1. GỘP TRÙNG: các bài cùng tiêu đề (key) → 1 mẫu.
       Nhãn lấy từ nguồn tin cậy nhất trong nhóm (người chấm > Claude > luật > tự gán),
       nhiều nhãn cùng nguồn thì theo đa số. Một tin đăng lại 30 lần chỉ tính như 1 tin.
       Mẫu đại diện = bài có nội dung dài nhất; article_id = id nhỏ nhất của nhóm
       → cả nhóm luôn cùng nằm ở train hoặc cùng ở kiểm định (không rò rỉ).
    2. CÂN BẰNG CÔNG TY: trọng số × sqrt(trung bình số mẫu mỗi công ty / số mẫu của công ty đó),
       kẹp trong [0.33, 3]. Công ty nhiều tin (VD NVL ~65% dữ liệu) bị giảm, công ty ít tin được tăng —
       dùng căn bậc hai để không đảo ngược hẳn tỷ lệ.
    """
    groups: dict[str, list[Sample]] = {}
    for s in samples:
        groups.setdefault(s.key or f"#{s.article_id}", []).append(s)

    merged: list[Sample] = []
    for members in groups.values():
        best_rank = max(SOURCE_RANK.get(m.source, 0) for m in members)
        top = [m for m in members if SOURCE_RANK.get(m.source, 0) == best_rank]
        votes = Counter(m.label for m in top)
        best = max(votes.values())
        label = max((m for m in top if votes[m.label] == best), key=lambda m: m.article_id).label
        rep = max((m for m in top if m.label == label), key=lambda m: len(m.text))
        merged.append(Sample(
            article_id=min(m.article_id for m in members), text=rep.text, label=label,
            weight=rep.weight, source=rep.source, key=rep.key, group=rep.group, dup_count=len(members),
        ))
    # Mẫu tự gán (pseudo) không bao giờ được rơi vào tập kiểm định
    merged = [m for m in merged if not (m.source == "pseudo" and ml_model.is_validation(m.article_id))]

    per_group = Counter(m.group or "_none" for m in merged)
    mean = len(merged) / max(len(per_group), 1)
    factor = {g: min(BALANCE_MAX, max(BALANCE_MIN, (mean / n) ** 0.5)) for g, n in per_group.items()}
    for m in merged:
        m.weight = round(m.weight * factor[m.group or "_none"], 4)

    stats = {
        "before_dedup": len(samples),
        "after_dedup": len(merged),
        "per_company": dict(per_group.most_common()),
        "company_weight": {g: round(f, 2) for g, f in sorted(factor.items(), key=lambda x: x[1])},
    }
    return merged, stats


def _score_model_on(bundle: ml_model.ModelBundle, samples: list[Sample]) -> dict:
    va = [s for s in samples if ml_model.is_validation(s.article_id)]
    if not va:
        return {}
    probs = bundle.predict_proba([s.text for s in va])
    y = np.array([LABEL_IDX[s.label] for s in va])
    return ml_model.evaluate(probs, y, [s.source for s in va])


async def run_learning() -> dict:
    """Chạy 1 vòng tự học. Trả về report (log / API admin)."""
    current = model_store.get_active() or await model_store.refresh_active()
    samples, info = await build_dataset(current)
    version = await model_store.next_version()

    bundle, report = await asyncio.to_thread(ml_model.train, samples, version)
    report.update(info)
    report["version"] = version

    if bundle is None:
        await model_store.save(None, version, report, "rejected", report["reason"])
        report["decision"] = "skipped"
        log.info(f"[learn] v{version} skipped: {report['reason']}")
        return report

    new_score = ml_model.headline_score(report)
    if current is not None:
        old_eval = _score_model_on(current, samples)
        old_score = ml_model.headline_score(old_eval)
        report["previous"] = {"version": current.version, **old_eval}
    else:
        old_score = None

    if old_score is None or new_score >= old_score:
        note = (f"Thay v{current.version} ({old_score:.3f} → {new_score:.3f})"
                if current else f"Mô hình đầu tiên (macro-F1 {new_score:.3f})")
        await model_store.save(bundle, version, report, "active", note)
        await model_store.refresh_active()
        report["decision"] = "adopted"
    else:
        note = f"Kém hơn v{current.version} ({new_score:.3f} < {old_score:.3f}) — giữ mô hình cũ"
        await model_store.save(bundle, version, report, "rejected", note)
        report["decision"] = "rejected"
    report["note"] = note
    log.info(f"[learn] v{version} {report['decision']}: {note}")
    return report


def format_report(report: dict) -> str:
    """Báo cáo ngắn gửi Telegram sau mỗi vòng tự học."""
    v = report.get("version")
    if report.get("decision") == "skipped":
        return (f"🧠 <b>TỰ HỌC v{v}</b> — chưa train\n{report.get('reason')}\n\n"
                f"Hãy bấm 🟢/🔴/⚪ dưới các tin để dạy bot.")
    src = report.get("sources", {})
    val = report.get("val_gold") or report.get("val", {})
    scope = "nhãn người dùng" if "val_gold" in report else "nhãn bạc (luật đọc toàn bài)"
    icon = {"adopted": "✅", "rejected": "↩️"}.get(report.get("decision"), "")
    lines = [
        f"🧠 <b>TỰ HỌC v{v}</b> {icon} {report.get('note', '')}",
        f"Dữ liệu: 👤 {src.get('gold', 0)} người dùng · 🤖 {src.get('llm', 0)} Claude · 📏 {src.get('silver', 0)} luật · 🔁 {src.get('pseudo', 0)} tự gán",
        f"Kiểm định ({scope}, {val.get('n', 0)} bài): đúng {val.get('accuracy', 0):.0%} · "
        f"macro-F1 {val.get('macro_f1', 0):.2f} · sai lệch % (ECE) {val.get('ece', 0):.1%}",
    ]
    return "\n".join(lines)
