"""
Lưu / nạp mô hình ML trong bảng ml_models (Postgres).
Giữ 1 bản active trong RAM để phân loại không phải query DB.
"""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import defer

from app.classifier.ml_model import ModelBundle
from app.db import AsyncSessionLocal
from app.db.models import MLModel

log = logging.getLogger(__name__)

ALGO = "tfidf-logreg-temp"
_active: ModelBundle | None = None


def get_active() -> ModelBundle | None:
    return _active


async def refresh_active() -> ModelBundle | None:
    """Nạp mô hình active mới nhất từ DB vào RAM."""
    global _active
    try:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(MLModel).where(MLModel.status == "active").order_by(MLModel.version.desc()).limit(1)
            )
        if row is None:
            _active = None
            log.info("[model] Chưa có mô hình ML — dùng rule-based")
        elif _active is None or _active.version != row.version:
            _active = ModelBundle.from_bytes(row.blob)
            log.info(f"[model] Đã nạp mô hình ML v{row.version}")
    except Exception as e:      # DB/pickle lỗi không được làm sập pipeline
        log.error(f"[model] Không nạp được mô hình: {e}")
    return _active


async def next_version() -> int:
    async with AsyncSessionLocal() as session:
        return (await session.scalar(select(func.max(MLModel.version))) or 0) + 1


async def save(bundle: ModelBundle | None, version: int, report: dict, status: str, note: str) -> None:
    """Lưu kết quả 1 lần train. status=active sẽ chuyển bản active cũ sang retired."""
    async with AsyncSessionLocal() as session:
        if status == "active":
            await session.execute(
                update(MLModel).where(MLModel.status == "active").values(status="retired")
            )
        session.add(MLModel(
            version=version,
            status=status,
            algo=ALGO,
            n_train=report.get("n_train"),
            n_gold=report.get("sources", {}).get("gold"),
            metrics=report,
            # Chỉ giữ blob của bản active — bản bị từ chối chỉ cần metrics để xem lịch sử
            blob=bundle.to_bytes() if (bundle and status == "active") else None,
            note=note,
        ))
        await session.commit()


async def history(limit: int = 5) -> list[MLModel]:
    async with AsyncSessionLocal() as session:
        result = await session.scalars(
            select(MLModel).options(defer(MLModel.blob)).order_by(MLModel.version.desc()).limit(limit)
        )
        return list(result.all())
