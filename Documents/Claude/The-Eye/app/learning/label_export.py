"""
Xuất file Markdown để chủ bot tự chạy LLM (VD Claude Haiku) dán nhãn — và nhập kết quả về.

Bot KHÔNG gọi LLM. Luồng:
  1. Hằng tuần (thứ Hai 08:05) hoặc /export_md [7d|14d]:
     Bao gửi file  bao_labels_<từ>_<đến>.md  vào chat chính, gồm:
       - Câu lệnh sẵn cho LLM + định dạng trả lời bắt buộc
       - Các tin trong khoảng thời gian, CHƯA được người dùng chấm và chưa có nhãn LLM,
         ưu tiên tin Bao kém chắc chắn nhất (học được nhiều nhất từ những tin này)
  2. Bạn dán file vào Haiku, nhận về các dòng:   1234 | POS | lý do ngắn
  3. Gửi lại cho Bao: /import <dán kết quả>  hoặc gửi file .md/.txt kèm chú thích /import
     → lưu vào training_labels với labeler="llm:import" → dùng ở lần tự học kế tiếp
       (trọng số thấp hơn nhãn người chấm, cao hơn nhãn từ khoá).
"""
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.db.models import ArticleContent, ArticleMeta, Company, TrainingLabel
from app.learning.feedback import HUMAN_PREFIX

LLM_LABELER = "llm:import"
VN_TZ = timezone(timedelta(hours=7))
MAX_ARTICLES = 150          # ~150 × 400 token ≈ 60K token / file — rẻ với Haiku
CONTENT_EXCERPT = 1200      # ký tự thân bài trích vào file

PROMPT = """Bạn là chuyên viên phân tích tin doanh nghiệp niêm yết Việt Nam.
Với MỖI bài bên dưới, đánh giá tin đó **tốt hay xấu cho cổ đông của công ty được nêu**:

- **POS** — tin tốt: lợi nhuận/doanh thu tăng, hợp đồng lớn, mở rộng, được khen thưởng/vinh danh, cổ tức cao...
- **NEG** — tin xấu: thua lỗ, bị phạt/điều tra/khởi tố, nợ xấu, mất hợp đồng, lãnh đạo bị bắt...
- **NEU** — trung tính: thông báo hành chính, lịch họp, giao dịch cổ đông thông thường, tin chung chung,
  hoặc bài không thực sự nói về công ty đó.

Đọc cả nội dung trích, không chỉ tiêu đề (VD: tiêu đề "nhận Huân chương" nhưng nội dung toàn tin tốt → POS).
Không bỏ sót bài nào."""

OUTPUT_FORMAT = """Chỉ trả lời các dòng theo đúng định dạng, mỗi bài 1 dòng, không thêm gì khác:

```
ID | NHÃN | lý do ngắn (≤ 15 từ)
```

Ví dụ:

```
1234 | POS | Nhận Huân chương Lao động, doanh thu tăng 18%
1235 | NEG | Bị UBCKNN phạt vì chậm công bố thông tin
1236 | NEU | Thông báo ngày đăng ký cuối cùng
```"""


def _clean(text: str | None, limit: int | None = None) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    if limit and len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "…"
    return t


async def build_markdown(days: int = 7, limit: int = MAX_ARTICLES) -> tuple[str, str, int]:
    """Trả về (tên file, nội dung markdown, số bài)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    async with AsyncSessionLocal() as session:
        labeled = select(TrainingLabel.article_id).where(
            TrainingLabel.labeler.like(f"{HUMAN_PREFIX}%") | (TrainingLabel.labeler == LLM_LABELER)
        )
        rows = await session.execute(
            select(ArticleMeta, Company, func.left(ArticleContent.content_raw, CONTENT_EXCERPT + 200))
            .join(Company, ArticleMeta.company_id == Company.id)
            .outerjoin(ArticleContent, ArticleContent.article_id == ArticleMeta.id)
            .where(ArticleMeta.published_at >= since)
            .where(ArticleMeta.id.not_in(labeled))
            # Tin Bao kém chắc nhất lên đầu; cùng mức thì tin mới hơn trước
            .order_by(func.coalesce(ArticleMeta.sentiment_score, 0).asc(), ArticleMeta.published_at.desc())
            .limit(limit)
        )
        items = rows.all()

    d_from = since.astimezone(VN_TZ).strftime("%d/%m")
    d_to = now.astimezone(VN_TZ).strftime("%d/%m/%Y")
    filename = f"bao_labels_{since.astimezone(VN_TZ):%Y%m%d}_{now.astimezone(VN_TZ):%Y%m%d}.md"

    lines = [
        f"# Bao — tin cần dán nhãn ({d_from} – {d_to})",
        "",
        f"{len(items)} bài chưa được chấm. Dán toàn bộ file này vào LLM, rồi gửi kết quả lại cho Bao bằng `/import`.",
        "",
        "## Yêu cầu",
        "",
        PROMPT,
        "",
        "## Định dạng trả lời",
        "",
        OUTPUT_FORMAT,
        "",
        "## Các bài",
    ]
    for art, company, content in items:
        lines += [
            "",
            f"### {art.id} · {company.ticker} · {_clean(company.name)}",
            f"- **Ngày:** {art.published_at.astimezone(VN_TZ):%d/%m/%Y %H:%M}",
            f"- **Tiêu đề:** {_clean(art.title)}",
        ]
        if art.summary:
            lines.append(f"- **Sapo:** {_clean(art.summary, 400)}")
        if content:
            lines.append(f"- **Nội dung (trích):** {_clean(content, CONTENT_EXCERPT)}")
    lines += ["", "---", "", "Hết danh sách. Nhớ trả lời đủ " f"{len(items)} dòng theo định dạng `ID | NHÃN | lý do`."]
    return filename, "\n".join(lines) + "\n", len(items)


# ─── Nhập kết quả LLM ────────────────────────────────────────────

_LINE_RE = re.compile(
    r"^\s*[-*|]?\s*#?(?P<id>\d{1,12})\s*[|:,\-–]\s*\**(?P<label>POS|NEG|NEU)\**\b(?:\s*[|:,\-–]\s*(?P<reason>.*))?$",
    re.IGNORECASE,
)


def parse_labels(text: str) -> dict[int, tuple[str, str]]:
    """Đọc các dòng `ID | NHÃN | lý do` (chấp nhận cả `ID: NHÃN`, `#ID - NHÃN`...). Dòng sau ghi đè dòng trước."""
    out: dict[int, tuple[str, str]] = {}
    for line in (text or "").splitlines():
        m = _LINE_RE.match(line.strip().strip("`"))
        if m:
            out[int(m.group("id"))] = (m.group("label").upper(), (m.group("reason") or "").strip(" |")[:200])
    return out


async def import_labels(labels: dict[int, tuple[str, str]]) -> dict:
    """Lưu nhãn LLM. Bỏ qua id không tồn tại. Trả về thống kê."""
    if not labels:
        return {"saved": 0, "unknown": 0, "by_label": {}}
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        existing = set((await session.scalars(
            select(ArticleMeta.id).where(ArticleMeta.id.in_(list(labels)))
        )).all())
        by_label: dict[str, int] = {}
        for aid in existing:
            label, _reason = labels[aid]
            stmt = pg_insert(TrainingLabel).values(
                article_id=aid, label=label, labeler=LLM_LABELER, confidence=0.8, created_at=now,
            )
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["article_id", "labeler"], set_={"label": label, "created_at": now},
            ))
            by_label[label] = by_label.get(label, 0) + 1
        await session.commit()
    return {"saved": len(existing), "unknown": len(labels) - len(existing), "by_label": by_label}
