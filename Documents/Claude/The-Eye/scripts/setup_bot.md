# Setup Telegram Bot cho The-Eye

## Bước 1 — Tạo bot với BotFather

1. Mở Telegram, tìm **@BotFather**
2. Gửi `/newbot`
3. Đặt tên: `The-Eye News Bot` (tên hiển thị)
4. Đặt username: `theeyenews_bot` (phải kết thúc bằng `bot`)
5. Copy **Bot Token** → điền vào `.env`:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

## Bước 2 — Lấy Chat ID

**Cách A — Chat riêng (chỉ bạn nhận):**
1. Tìm bot vừa tạo → gửi `/start`
2. Truy cập: `https://api.telegram.org/bot{TOKEN}/getUpdates`
3. Tìm `"chat":{"id": XXXXXXXX}` → đó là Chat ID của bạn

**Cách B — Group (nhiều người nhận):**
1. Tạo group Telegram
2. Thêm bot vào group
3. Gửi `/start@theeyenews_bot` trong group
4. Truy cập URL trên → Chat ID của group (số âm, VD: `-1001234567890`)

```
TELEGRAM_CHAT_ID=-1001234567890
```

## Bước 3 — Cấu hình bot trong Group

Trong BotFather:
```
/setprivacy → chọn bot → DISABLE
```
> Cho phép bot đọc tin nhắn trong group (mặc định bot chỉ đọc được lệnh `/`)

## Bước 4 — Test

```bash
# Test gửi tin
python scripts/test_notify.py

# Test report builder (không cần Telegram)
python scripts/test_bot.py VIC
python scripts/test_bot.py --all
python scripts/test_bot.py --top neg 7d

# Chạy thật (cần DB)
python main.py
```

## Danh sách lệnh trong group

| Lệnh | Ví dụ | Mô tả |
|------|-------|-------|
| `/report TICKER [range]` | `/report VIC 48h` | Báo cáo 1 công ty |
| `/all [range]` | `/all 7d` | Tổng quan tất cả |
| `/top pos\|neg [range]` | `/top neg 7d` | Top tin POS/NEG |
| `/list` | `/list` | Danh sách ticker |
| `/status` | `/status` | Trạng thái hệ thống |
| `/help` | `/help` | Hướng dẫn |

**Range:** `24h` (mặc định) · `48h` · `7d`

## Thêm bạn bè vào group

Chỉ cần thêm vào group Telegram — ai trong group đều dùng được lệnh.
Bot trả lời **trong group** (không phải DM riêng).
