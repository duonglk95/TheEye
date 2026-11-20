"""
HTTP API nhỏ chạy cùng bot (aiohttp) — cho Scheduled Task của Claude Code chấm nhãn hằng tuần.

  GET  /healthz                         → "ok" (không cần khoá)
  GET  /api/labeling/pending?days=7&limit=150
       → {"instructions": "...", "articles": [{id, ticker, company, published, title, summary, content}]}
  GET  /api/labeling/pending?relabel=1&days=3650&limit=200&after_id=0
       → chấm lại TẤT CẢ bài (trừ bài người dùng đã chấm), phân trang theo id; "next_after_id" cho trang sau
  POST /api/admin/train                → chạy tự học ngay, trả báo cáo (độ chính xác, ECE, dữ liệu)
  GET  /api/admin/unlinked              → bài không gắn công ty (kiểm tra)
  POST /api/labeling/labels
       body {"labeler": "claude-haiku", "labels": [{"id": 123, "label": "POS", "reason": "..."}]}
       → {"saved": n, "unknown_ids": [...], "by_label": {...}, "errors": [...]}

Bảo vệ: header  Authorization: Bearer <LABEL_API_TOKEN>  (biến môi trường trên Railway).
Không đặt LABEL_API_TOKEN → API không được bật (chỉ /healthz).
"""
import hmac
import logging
import os

from aiohttp import web

from app.learning.label_export import INSTRUCTIONS, fetch_pending, import_labels, validate_labels

log = logging.getLogger(__name__)
MAX_BODY = 2 * 1024 * 1024


def is_authorized(header: str | None, token: str | None) -> bool:
    if not token or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[len("Bearer "):].strip().encode(), token.encode())


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def build_app(token: str | None) -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)

    async def healthz(_request):
        return web.Response(text="ok")

    @web.middleware
    async def auth(request, handler):
        if request.path.startswith("/api/") and not is_authorized(request.headers.get("Authorization"), token):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def pending(request):
        relabel = request.query.get("relabel") in ("1", "true", "yes")
        days = _int(request.query.get("days"), 7, 1, 3650)
        limit = _int(request.query.get("limit"), 150, 1, 500)
        after_id = _int(request.query.get("after_id"), 0, 0, 10**12)
        articles = await fetch_pending(days, limit, relabel=relabel, after_id=after_id)
        body = {"instructions": INSTRUCTIONS, "count": len(articles), "articles": articles}
        if relabel:
            body["next_after_id"] = articles[-1]["id"] if len(articles) == limit else None
        return web.json_response(body)

    async def labels(request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "body phải là JSON"}, status=400)
        parsed, errors = validate_labels(body.get("labels") if isinstance(body, dict) else None)
        labeler = str((body or {}).get("labeler") or "claude-task")
        result = await import_labels(parsed, labeler=labeler)
        if result["saved"]:
            from app.learning.train_trigger import AFTER_LLM_LABELS_SEC, request_training
            request_training(AFTER_LLM_LABELS_SEC)      # chấm xong thì học luôn
        log.info(f"[labeling-api] {labeler}: saved {result['saved']} {result['by_label']}, errors {len(errors)}")
        return web.json_response({**result, "errors": errors[:50]})

    async def unlinked(request):
        """Bài không gắn công ty nào (VD bị gỡ sau khi sửa từ khoá) — chỉ đọc, để kiểm tra."""
        from sqlalchemy import select
        from app.db import AsyncSessionLocal
        from app.db.models import ArticleMeta
        limit = _int(request.query.get("limit"), 300, 1, 1000)
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(ArticleMeta.id, ArticleMeta.title, ArticleMeta.published_at)
                .where(ArticleMeta.company_id == None)  # noqa: E711
                .order_by(ArticleMeta.published_at.desc()).limit(limit)
            )
            items = [{"id": i, "title": t, "published": p.isoformat()} for i, t, p in rows.all()]
        return web.json_response({"count": len(items), "articles": items})

    async def train(_request):
        """Chạy 1 vòng tự học ngay (thay cho lệnh trong bot — giao diện Bao chỉ dành cho người dùng cuối)."""
        from app.learning.trainer import run_learning
        report = await run_learning()
        return web.json_response(report, dumps=lambda o: __import__("json").dumps(o, ensure_ascii=False, default=str))

    app.router.add_get("/healthz", healthz)
    if token:
        app.router.add_get("/api/admin/unlinked", unlinked)
        app.router.add_post("/api/admin/train", train)
        app.middlewares.append(auth)
        app.router.add_get("/api/labeling/pending", pending)
        app.router.add_post("/api/labeling/labels", labels)
    return app


async def start_api() -> web.AppRunner | None:
    """Khởi động server trên $PORT (Railway cấp). Trả về runner để dừng khi tắt."""
    token = os.environ.get("LABEL_API_TOKEN")
    port = int(os.environ.get("PORT", "8080"))
    runner = web.AppRunner(build_app(token), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info(f"[api] listening on :{port} — labeling API {'ON' if token else 'OFF (chưa đặt LABEL_API_TOKEN)'}")
    return runner
