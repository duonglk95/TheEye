# 👁 The-Eye — Trợ lý theo dõi tin doanh nghiệp

> **Dành cho ai?** Tài liệu này viết cho người **không cần biết code** vẫn cài và dùng được.
> Chỉ cần làm theo từng bước, copy-paste lệnh khi cần.

---

## 📖 Mục lục

1. [The-Eye là gì?](#1-the-eye-là-gì)
2. [Hệ thống hoạt động như thế nào?](#2-hệ-thống-hoạt-động-như-thế-nào)
3. [Chuẩn bị trước khi cài](#3-chuẩn-bị-trước-khi-cài)
4. [Cài đặt lần đầu](#4-cài-đặt-lần-đầu)
5. [Thiết lập Telegram Bot](#5-thiết-lập-telegram-bot)
6. [Thiết lập cơ sở dữ liệu (Railway)](#6-thiết-lập-cơ-sở-dữ-liệu-railway)
7. [Chạy thử trên máy](#7-chạy-thử-trên-máy)
8. [Giao diện terminal (TUI)](#8-giao-diện-terminal-tui)
9. [Lệnh Telegram Bot trong group](#9-lệnh-telegram-bot-trong-group)
10. [Deploy lên Railway (chạy 24/7)](#10-deploy-lên-railway-chạy-247)
11. [Thêm / bớt công ty theo dõi](#11-thêm--bớt-công-ty-theo-dõi)
12. [Chỉnh sửa từ khóa tích cực / tiêu cực](#12-chỉnh-sửa-từ-khóa-tích-cực--tiêu-cực)
12b. [Bao tự học — đọc toàn bài & ý nghĩa con số %](#12b-bao-tự-học--đọc-toàn-bài--ý-nghĩa-con-số-)
13. [Câu hỏi thường gặp](#13-câu-hỏi-thường-gặp)

---

## 1. The-Eye là gì?

**The-Eye** là một chương trình tự động:

- 🔍 **Quét tin tức** từ CafeF, Vietstock, VnExpress, Google News mỗi 5 phút
- 🏷️ **Phân loại tự động** mỗi bài báo thành 3 nhóm:
  - 🟢 **Tích cực (POS)** — tin tốt cho doanh nghiệp
  - 🔴 **Tiêu cực (NEG)** — tin xấu, rủi ro
  - ⚪ **Trung lập (NEU)** — thông báo, thông tin thường
- 📱 **Gửi cảnh báo Telegram** ngay khi có tin tích cực/tiêu cực quan trọng
- 📊 **Tổng hợp báo cáo** gửi vào group Telegram mỗi 2 tiếng
- 💬 **Trả lời lệnh** khi bạn hoặc bạn bè hỏi trong group Telegram

**5 công ty đang theo dõi:**

| Mã CK | Tên công ty |
|-------|-------------|
| SBT | TTC AgriS (Thành Thành Công - Biên Hòa) |
| DGC | Hóa chất Đức Giang |
| NAF | Nafoods Group |
| VIC | Vingroup |
| CTD | Coteccons |

---

## 2. Hệ thống hoạt động như thế nào?

```
Mỗi 5 phút:
  CafeF ──┐
Vietstock ─┼──► Lọc tin liên quan ──► Phân loại ──► Lưu vào cơ sở dữ liệu
VnExpress ─┘       (theo công ty)      POS/NEG/NEU
Google News ─┘

                                            │
                              ┌─────────────┴──────────────┐
                              ▼                            ▼
                    Tin POS/NEG?              Mỗi 2 tiếng (8h–22h):
                    → Gửi NGAY               → Gửi bản tóm tắt
                      vào Telegram             vào Telegram

Khi bạn nhắn lệnh trong group:
  /report VIC  ──► Tổng hợp tin VIC 24h ──► Gửi lại vào group
```

---

## 3. Chuẩn bị trước khi cài

Bạn cần cài 2 thứ vào máy. Làm **1 lần duy nhất**.

### 3.1 Cài Python

1. Truy cập: **https://www.python.org/downloads/**
2. Nhấn nút vàng **"Download Python 3.12.x"**
3. Chạy file vừa tải, **TÍCH VÀO Ô "Add Python to PATH"** trước khi nhấn Install
4. Nhấn **Install Now**

> ✅ Kiểm tra: Mở Terminal (Mac) hoặc Command Prompt (Windows), gõ `python --version`
> → Nếu thấy `Python 3.12.x` là thành công

### 3.2 Mở Terminal / Command Prompt

- **Mac:** Nhấn `Cmd + Space` → gõ `Terminal` → Enter
- **Windows:** Nhấn `Windows + R` → gõ `cmd` → Enter

> 💡 **Terminal là gì?** Là cửa sổ đen/trắng để nhập lệnh. Bạn chỉ cần copy-paste lệnh từ hướng dẫn này vào đó.

---

## 4. Cài đặt lần đầu

### Bước 1 — Vào thư mục dự án

Mở Terminal, gõ lệnh sau (thay đường dẫn nếu cần):

```bash
cd /Users/duonglk/Documents/Claude/The-Eye
```

> 💡 `cd` = "change directory" = đi vào thư mục

### Bước 2 — Tạo môi trường Python riêng

```bash
python -m venv venv
```

Sau đó **kích hoạt** môi trường:

- **Mac/Linux:**
  ```bash
  source venv/bin/activate
  ```
- **Windows:**
  ```bash
  venv\Scripts\activate
  ```

> ✅ Thành công khi thấy `(venv)` xuất hiện ở đầu dòng lệnh

### Bước 3 — Cài thư viện cần thiết

```bash
pip install -r requirements.txt
```

> ⏳ Chờ khoảng 2–3 phút. Thấy chữ "Successfully installed..." là xong.

### Bước 4 — Tạo file cấu hình

```bash
cp .env.example .env
```

Sau đó **mở file `.env`** bằng bất kỳ trình soạn thảo nào (Notepad, TextEdit...) và điền thông tin vào. Xem hướng dẫn ở **Bước 5 và 6** bên dưới.

---

## 5. Thiết lập Telegram Bot

### 5.1 Tạo Bot

1. Mở Telegram → tìm kiếm **@BotFather** → nhấn **Start**
2. Gõ lệnh: `/newbot`
3. BotFather hỏi **"Alright, a new bot. How are we going to call it?"**
   → Trả lời: `The Eye News Bot`
4. BotFather hỏi tên username (phải kết thúc bằng `bot`)
   → Trả lời ví dụ: `mytheeyenews_bot`
5. BotFather gửi lại một đoạn văn bản, trong đó có dòng:
   ```
   Use this token to access the HTTP API:
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   → **Copy dãy số và chữ đó** (đó là Bot Token)

6. Mở file `.env`, tìm dòng `TELEGRAM_BOT_TOKEN=` và dán vào:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

### 5.2 Tắt chế độ Privacy (để bot đọc được lệnh trong group)

1. Vẫn trong chat với **@BotFather**
2. Gõ: `/setprivacy`
3. Chọn bot vừa tạo
4. Chọn **DISABLE**

> ⚠️ Nếu bỏ qua bước này, bot sẽ không phản hồi lệnh trong group!

### 5.3 Lấy Chat ID

**Nếu muốn nhận tin riêng (chỉ mình bạn):**
1. Tìm bot vừa tạo trên Telegram → nhấn **Start**
2. Mở trình duyệt, truy cập:
   ```
   https://api.telegram.org/bot{TOKEN_CỦA_BẠN}/getUpdates
   ```
   (Thay `{TOKEN_CỦA_BẠN}` bằng token thật)
3. Tìm đoạn `"chat":{"id":` → số phía sau là Chat ID của bạn (VD: `123456789`)

**Nếu muốn nhận tin trong group (nhiều người):**
1. Tạo group Telegram mới
2. Thêm bot vào group
3. Gõ `/start@tên_bot_của_bạn` trong group
4. Làm tương tự bước 2-3 ở trên → Chat ID của group là **số âm** (VD: `-1001234567890`)

5. Điền vào `.env`:
   ```
   TELEGRAM_CHAT_ID=-1001234567890
   ```

### 5.4 Kiểm tra bot hoạt động

```bash
python scripts/test_notify.py
```

> ✅ Nếu nhận được tin nhắn trong Telegram là thành công!

---

## 6. Thiết lập cơ sở dữ liệu (Railway)

> 💡 **Cơ sở dữ liệu** là nơi lưu trữ tất cả bài báo đã thu thập. Railway cung cấp miễn phí.

### Bước 1 — Tạo tài khoản Railway

1. Truy cập: **https://railway.app**
2. Nhấn **"Login with GitHub"** (cần có tài khoản GitHub, tạo miễn phí tại github.com)

### Bước 2 — Tạo PostgreSQL database

1. Vào Railway dashboard → nhấn **"New Project"**
2. Chọn **"Deploy PostgreSQL"**
3. Chờ vài giây → database được tạo
4. Nhấn vào database vừa tạo → tab **"Connect"**
5. Copy dòng **"Postgres Connection URL"** trông như:
   ```
   postgresql://postgres:mậtkhẩu@roundhouse.proxy.rlwy.net:12345/railway
   ```
6. Điền vào `.env`:
   ```
   DATABASE_URL=postgresql://postgres:mậtkhẩu@roundhouse.proxy.rlwy.net:12345/railway
   ```

### Bước 3 — Khởi tạo cơ sở dữ liệu

```bash
python scripts/run_seed.py
```

> ✅ Thấy "Done." là đã tạo xong bảng và điền dữ liệu ban đầu.

---

## 7. Chạy thử trên máy

### Thử giao diện terminal (không cần internet, không cần database)

```bash
python main.py --demo
```

> Màn hình terminal sẽ hiện giao diện The-Eye với dữ liệu giả để bạn xem trước.
> Nhấn `Q` để thoát.

### Chạy thật (cần đã điền `.env` đầy đủ)

```bash
python main.py --tui
```

### Chạy dịch vụ nền (không có giao diện, chỉ chạy ngầm)

```bash
python main.py
```

---

## 8. Giao diện terminal (TUI)

Khi chạy `python main.py --demo` hoặc `--tui`, bạn thấy màn hình như sau:

```
┌──────────────────────────────────────────────────────────────────┐
│  👁 The-Eye                                          14:32:07    │
├──────────────────┬───────────────────────────────────────────────┤
│  ╔══════════════╗ │  📰 27 bài/24h  🟢 8   🔴 3   ⚪ 16  ● LIVE │
│  ║  👁 THE EYE ║ │──────────────────────────────────────────────│
│  ╚══════════════╝ │ Giờ    Ticker  Nhãn      %   Tiêu đề        │
│                   │ 09:30  VIC    🟢 POS   89%  Vingroup ký...  │
│  CÔNG TY          │ 08:15  DGC    🔴 NEG   81%  Hóa chất bị... │
│  ─────────────── │ 10:00  VIC    🟢 POS   77%  Vinhomes bàn... │
│  [●] Tất cả       │ 14:05  NAF    🟢 POS   83%  Nafoods ký HĐ  │
│  [SBT] TTC AgriS 3│ 11:20  CTD    ⚪ NEU   58%  Coteccons...   │
│  [DGC] Đức Giang 7│                                             │
│  [NAF] Nafoods   2│                                             │
│  [VIC] Vingroup 11│                                             │
│  [CTD] Coteccons 4│                                             │
│                   │                                             │
│  FILTER           │                                             │
│  [1] Tất cả ◀     │                                             │
│  [2] 🟢 Tích cực  │                                             │
│  [3] 🔴 Tiêu cực  │                                             │
│  [4] ⚪ Trung lập  │                                             │
│                   │  / Tìm kiếm theo tiêu đề, ticker...        │
└──────────────────┴───────────────────────────────────────────────┘
   [R] Refresh  [D] Digest  [C] Config  [L] Logs  [Q] Thoát
```

### Phím tắt

| Phím | Tác dụng |
|------|----------|
| `R` | Làm mới dữ liệu |
| `D` | Gửi digest Telegram ngay |
| `C` | Xem cấu hình hệ thống |
| `L` | Xem nhật ký hệ thống |
| `1` | Hiện tất cả tin |
| `2` | Chỉ hiện tin 🟢 Tích cực |
| `3` | Chỉ hiện tin 🔴 Tiêu cực |
| `4` | Chỉ hiện tin ⚪ Trung lập |
| `Enter` | Xem chi tiết bài báo đang chọn |
| `/` | Tìm kiếm theo tiêu đề hoặc mã cổ phiếu |
| `Esc` | Đóng cửa sổ popup / Xóa filter |
| `Q` | Thoát chương trình |

---

## 9. Lệnh Telegram Bot trong group

Sau khi đã thêm bot vào group, bạn hoặc bạn bè có thể gõ các lệnh sau:

---

### `/report TICKER` — Báo cáo chi tiết 1 công ty

```
/report VIC
/report SBT 48h
/report DGC 7d
```

**Kết quả nhận được:**
```
📊 BÁO CÁO: [VIC] Vingroup
⏱ 24h qua  •  Cập nhật lúc 14:32 30/05/2026
─────────────────────────
📰 Tổng: 11 bài  │  🟢 4  🔴 2  ⚪ 5
🟡 Tín hiệu HỖN HỢP

📈 TIN TÍCH CỰC:
  🟢 [89%] Vingroup ký kết hợp tác chiến lược...
  🟢 [77%] Vinhomes bàn giao dự án đúng tiến độ...

📉 TIN TIÊU CỰC:
  🔴 [72%] VinFast ghi nhận khoản lỗ Q1/2026...
```

**Khoảng thời gian hỗ trợ:**
- `24h` — 24 giờ qua *(mặc định nếu không ghi)*
- `48h` — 2 ngày qua
- `7d` — 7 ngày qua

---

### `/all` — Tổng quan tất cả công ty

```
/all
/all 7d
```

**Kết quả:**
```
📋 TỔNG QUAN — 24h QUA
⏱ Cập nhật lúc 14:32 30/05/2026
═════════════════════════
↑ [CTD] Coteccons          🟢2 ⚪2  (4 bài)
↓ [DGC] Hóa chất Đức Giang 🔴1 ⚪6  (7 bài)
→ [NAF] Nafoods Group      🟢1 ⚪1  (2 bài)
↓ [SBT] TTC AgriS          ⚪3      (3 bài)
↓ [VIC] Vingroup           🟢4 🔴2 ⚪5  (11 bài)
─────────────────────────
Dùng /report TICKER để xem chi tiết
```

---

### `/top pos` hoặc `/top neg` — Tin nổi bật nhất

```
/top pos
/top neg
/top neg 7d
```

**Kết quả:**
```
🔴 TOP 5 TIN TIÊU CỰC — 24h QUA

1. [DGC] 🔴 81%
   Hóa chất Đức Giang bị phạt vi phạm...
   08:15 30/05  Vietstock

2. [VIC] 🔴 72%
   VinFast ghi nhận khoản lỗ lớn Q1/2026
   15:30 30/05  CafeF
...
```

---

### `/list` — Danh sách công ty đang theo dõi

```
/list
```

---

### `/status` — Kiểm tra hệ thống có đang chạy không

```
/status
```

**Kết quả:**
```
⚙️ TRẠNG THÁI HỆ THỐNG
14:32:05 30/05/2026

  🗄 Database  : ✅ Online
  📡 RSS Poll  : ✅ mỗi 5 phút
  🔔 Digest    : ✅ mỗi 2 tiếng
  🤖 Bot       : ✅ Online

  📊 24h qua:
    Tổng bài  : 27
    🟢 POS    : 8
    🔴 NEG    : 3
    ⚪ NEU    : 16
```

---

### `/help` — Xem tất cả lệnh

```
/help
```

---

## 10. Deploy lên Railway (chạy 24/7)

Sau khi test ổn trên máy, deploy để chạy liên tục không cần mở máy tính.

### Bước 1 — Cài Railway CLI

```bash
npm install -g @railway/cli
```

> 💡 Nếu máy chưa có `npm`: tải tại **https://nodejs.org** → chọn LTS → cài đặt

### Bước 2 — Đăng nhập Railway

```bash
railway login
```

> Trình duyệt sẽ mở ra → đăng nhập bằng GitHub → quay lại Terminal

### Bước 3 — Kết nối với project Railway

```bash
railway link
```

> Chọn project đã tạo ở Bước 6

### Bước 4 — Thêm biến môi trường

```bash
railway variables set TELEGRAM_BOT_TOKEN=token_của_bạn
railway variables set TELEGRAM_CHAT_ID=chat_id_của_bạn
railway variables set LOG_LEVEL=INFO
railway variables set ENVIRONMENT=production
```

> 💡 `DATABASE_URL` Railway tự thêm vì database cùng project

### Bước 5 — Deploy

```bash
railway up
```

> ⏳ Chờ 2–3 phút. Thấy **"Deployment successful"** là xong!

### Bước 6 — Kiểm tra

```bash
railway logs
```

> ✅ Nếu thấy "Scheduler started." và "Telegram Bot: polling started" là hệ thống đang chạy 24/7.

---

## 11. Thêm / bớt công ty theo dõi

Mở file **`config/companies.yaml`** bằng bất kỳ trình soạn thảo văn bản nào.

### Thêm công ty mới

Copy một khối công ty có sẵn và điền thông tin mới:

```yaml
  - ticker: HPG              # ← Mã cổ phiếu trên sàn
    name: "Hòa Phát Group"   # ← Tên ngắn
    full_name: "Tập đoàn Hòa Phát"  # ← Tên đầy đủ
    aliases:
      - "Hòa Phát"
      - "HPG"
    keywords:
      - "HPG"
      - "Hòa Phát"
      - "Tập đoàn Hòa Phát"
    sector: "Thép - Công nghiệp"
    exchange: HOSE
    active: true             # ← true = đang theo dõi, false = tạm dừng
```

### Tạm dừng theo dõi 1 công ty (không xóa)

Tìm công ty cần tạm dừng, đổi `active: true` thành `active: false`.

### Cập nhật vào hệ thống

Sau khi lưu file, chạy:
```bash
python scripts/run_seed.py
```

---

## 12. Chỉnh sửa từ khóa tích cực / tiêu cực

Mở file **`config/sentiment.yaml`**.

### Thêm từ khóa tích cực

Tìm phần `positive: → strong:` và thêm từ khóa:

```yaml
positive:
  strong:
    - "lợi nhuận tăng"
    - "ký kết hợp đồng"
    - "từ khóa mới của bạn"   # ← thêm vào đây
```

### Thêm từ khóa tiêu cực

Tìm phần `negative: → strong:` và thêm:

```yaml
negative:
  strong:
    - "thua lỗ"
    - "khởi tố"
    - "từ khóa xấu mới"       # ← thêm vào đây
```

> ✅ **Không cần khởi động lại** — hệ thống tự đọc file mới trong lần phân loại tiếp theo.

---

## 12b. Bao tự học — đọc toàn bài & ý nghĩa con số %

### Bao đọc tin thế nào?

1. **Đọc nhanh** (ngay khi lấy RSS): chỉ tiêu đề + sapo.
2. **Đọc toàn bài** (10 phút sau, khi đã tải được nội dung): chấm từng câu trong thân bài.
   Tin kiểu *"AgriS nhận Huân chương Lao động"* — tiêu đề không có chữ "tăng/lãi", nhưng thân bài toàn câu tích cực — sẽ được chuyển ⚪ → 🟢.
   Nếu đọc toàn bài thấy 🔴, bot gửi cảnh báo ngay.
   *(Bài từ Google News không tải được nội dung vì link là trang chuyển hướng — chỉ đọc tiêu đề.)*

### Dùng bot không cần gõ lệnh

Bấm **Start** (hoặc gõ `/menu` một lần), bàn phím gõ chữ được thay bằng các nút luôn hiện sẵn:
`📊 SBT` `📊 DGC` `📊 NAF` `📊 VIC` `📊 CTD` · `📋 Tổng quan` `🟢 Tin tốt` `🔴 Tin xấu` · `🔔 Bật/🔕 Tắt thông báo` (chat riêng).
Chạm 1 nút là ra báo cáo 24h.

> Trong group: cần tắt Privacy Mode (BotFather → `/setprivacy` → Disable) để bot thấy nút được chạm.

### Dạy Bao (chỉ admin)

Giao diện Bao dành cho người dùng cuối: không có nút chấm, không có thông tin training.
**Admin** (chủ bot — `ADMIN_USER_IDS`, mặc định là `TELEGRAM_CHAT_ID` nếu đó là chat riêng) khi xem tin trong
chat riêng với Bao sẽ thấy thêm hàng nút **🔴 Xấu · ⚪ Thường · 🟢 Tốt** dưới mỗi tin; có thêm lệnh ẩn `/fix`, `/why`.

Hằng ngày (T2–T6, 04:55) một Scheduled Task của Claude Code dùng Haiku chấm các tin mới qua API của bot
(`/api/labeling/*`, khoá `LABEL_API_TOKEN`). Khi train, các bài trùng tiêu đề được gộp làm 1 và trọng số được
cân lại giữa các công ty để công ty nhiều tin (VD NVL) không lấn át.

Mỗi đêm 02:30 Bao tự học (scikit-learn, không dùng LLM) từ các lượt chấm này và chỉ dùng mô hình mới nếu nó tốt hơn bản cũ. Quá trình này chạy ngầm, không gửi thông báo vào group.

### Con số %

Chỉ hiện ở tin cảnh báo **khi Bao đã tự học**: `82%` nghĩa là trong 100 tin Bao chấm ~82%, khoảng 82 tin đúng (đã kiểm chứng trên tin Bao chưa từng học). Trước đó không hiện %.

Lệnh ẩn: `/commands` (danh sách đầy đủ). Admin: `/why 1234`, `/fix 1234 pos|neg|neu`. Train ngay: `POST /api/admin/train` (khoá API).

> Cần ít nhất ~40 bài có nhãn rõ để train lần đầu. Trước đó bot dùng từ khoá (hiện `~%`).

---

## 13. Câu hỏi thường gặp

---

**❓ Bot Telegram không phản hồi lệnh trong group?**

→ Kiểm tra: BotFather → `/setprivacy` → tên bot → chọn **DISABLE**
→ Kiểm tra: Bot đã được thêm vào group chưa?

---

**❓ Lệnh `/report VIC` trả về "Không có tin nào"?**

→ Hệ thống mới chạy, chưa thu thập đủ tin. Chờ 5–10 phút rồi thử lại.
→ Kiểm tra `/status` xem hệ thống có đang chạy không.

---

**❓ Terminal hiện "ModuleNotFoundError"?**

→ Chưa kích hoạt môi trường. Chạy:
- Mac: `source venv/bin/activate`
- Windows: `venv\Scripts\activate`

---

**❓ Terminal hiện "DATABASE_URL not set"?**

→ Chưa điền file `.env`. Kiểm tra lại **Bước 4** và **Bước 6**.

---

**❓ Muốn thay đổi giờ gửi digest (hiện là 8h–22h mỗi 2 tiếng)?**

→ Mở `app/collector/scheduler.py`, tìm dòng:
```python
CronTrigger(hour="8,10,12,14,16,18,20,22", minute=0)
```
→ Sửa các số giờ theo ý muốn.

---

**❓ Muốn nhận thông báo về cả tin trung lập (NEU)?**

→ Mở `app/collector/scheduler.py`, tìm dòng:
```python
urgent = [aid for aid, label in results.items() if label in ("POS", "NEG")]
```
→ Sửa thành:
```python
urgent = [aid for aid, label in results.items() if label in ("POS", "NEG", "NEU")]
```

---

**❓ Railway báo lỗi khi deploy?**

→ Chạy `railway logs` để xem chi tiết lỗi
→ Kiểm tra tất cả biến môi trường đã được set chưa: `railway variables`

---

**❓ Muốn xóa toàn bộ dữ liệu cũ và bắt đầu lại?**

→ Vào Railway → database → chạy lệnh SQL:
```sql
TRUNCATE article_meta, article_content, training_labels CASCADE;
```

---

## 📞 Liên hệ hỗ trợ

Nếu gặp vấn đề không giải quyết được, cung cấp:
1. Nội dung lỗi (copy toàn bộ chữ đỏ trong terminal)
2. Bước bạn đang thực hiện

---

*👁 The-Eye — News Intelligence Monitor*
*Phiên bản hiện tại: Phase 2 (RSS + đọc toàn bài + ML tự học có hiệu chỉnh + Telegram Bot)*
