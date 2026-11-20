"""Đảm bảo mọi job mà start_scheduler() đăng ký đều tồn tại (tránh NameError khi khởi động)."""
import ast
from pathlib import Path


def test_all_scheduled_jobs_are_defined():
    src = (Path(__file__).parent.parent / "app" / "collector" / "scheduler.py").read_text()
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    imported = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    used = {
        call.args[0].id
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "add_job"
        and call.args and isinstance(call.args[0], ast.Name)
    }
    assert used, "không tìm thấy add_job nào"
    assert used <= defined | imported, f"job chưa định nghĩa: {used - defined - imported}"
