import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
# Module app.db đọc DATABASE_URL lúc import; engine không kết nối cho tới khi dùng
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")
