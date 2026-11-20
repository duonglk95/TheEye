"""
Chấm xong thì học luôn — không đợi lịch cố định.

Mỗi khi có nhãn mới, gọi request_training(delay). Bot đợi `delay` giây kể từ nhãn CUỐI CÙNG
(debounce: nhãn mới đến thì tính lại từ đầu) rồi mới train, để một đợt nhiều lô nhãn
(VD Haiku gửi 5 lô liên tiếp) chỉ train 1 lần.

  Nhãn từ Claude Haiku (API)   → train sau 2 phút
  Admin chấm tay (nút / /fix)  → train sau 10 phút (thường chấm liền nhiều tin)
  Bot khởi động lại            → nếu có nhãn mới hơn mô hình đang dùng thì train bù

job_train_if_due() được scheduler gọi mỗi phút.
"""
import logging
import time

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import MLModel, TrainingLabel

log = logging.getLogger(__name__)

AFTER_LLM_LABELS_SEC = 120
AFTER_ADMIN_LABELS_SEC = 600

_due_at: float | None = None
_running = False


def request_training(delay_sec: float) -> None:
    """Hẹn train sau `delay_sec` giây; gọi lại trước khi đến hạn thì dời hạn ra sau."""
    global _due_at
    _due_at = time.monotonic() + delay_sec
    log.info(f"[train] hẹn tự học sau {int(delay_sec)}s (có nhãn mới)")


def is_due(now: float | None = None) -> bool:
    return _due_at is not None and (now if now is not None else time.monotonic()) >= _due_at


async def labels_newer_than_model() -> bool:
    """Có nhãn (người / LLM) tạo sau lần train gần nhất không?"""
    async with AsyncSessionLocal() as session:
        last_label = await session.scalar(select(func.max(TrainingLabel.created_at)))
        last_train = await session.scalar(select(func.max(MLModel.created_at)))
    return last_label is not None and (last_train is None or last_label > last_train)


async def job_train_if_due() -> None:
    global _due_at, _running
    if not is_due() or _running:
        return
    _due_at, _running = None, True
    try:
        from app.learning.trainer import run_learning
        report = await run_learning()
        log.info(f"[train] v{report.get('version')} {report.get('decision')}: "
                 f"{report.get('note') or report.get('reason', '')}")
    except Exception as e:
        log.exception(f"[train] failed: {e}")
    finally:
        _running = False
