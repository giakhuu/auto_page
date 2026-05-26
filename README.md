# Hệ thống Tự động hóa Xuất bản Video Fanpage

## 1. Tổng quan dự án

Đây là dự án xây dựng một hệ thống tự động hóa nội dung đầu-cuối (end-to-end automation pipeline), cho phép người dùng gửi một đường dẫn video bất kỳ từ điện thoại qua Telegram Bot, sau đó hệ thống sẽ tự động tải video về máy chủ cục bộ, mở trình duyệt bằng Playwright với phiên đăng nhập Facebook có sẵn và thực hiện quy trình đăng tải video lên Fanpage như một người dùng thật.

Mục tiêu chính của dự án là rút ngắn thời gian vận hành, giảm thao tác thủ công lặp lại và tạo ra một luồng đăng tải nội dung linh hoạt, dễ mở rộng, không phụ thuộc vào Facebook Graph API.

## 2. Mục tiêu sản phẩm

### Mục tiêu chức năng

- Nhận link video từ Telegram Bot.
- Tải video nguồn từ link bằng `yt-dlp`.
- Kiểm tra file, metadata và lưu trữ tạm.
- Mở Facebook Fanpage bằng Playwright.
- Tự động upload video, nhập caption và xuất bản bài viết.
- Trả kết quả thành công hoặc thất bại về Telegram Bot.
- Lưu log để theo dõi, debug và retry khi cần.

### Mục tiêu kỹ thuật

- Dễ chạy trên máy local Windows trước, có thể mở rộng sang VPS sau.
- Kiến trúc module rõ ràng để dễ bảo trì.
- Tách riêng các lớp `bot`, `download`, `publish`, `storage`, `config`, `logging`.
- Có cơ chế retry, timeout và chụp ảnh màn hình khi lỗi.
- Dễ nâng cấp thêm nhiều page, nhiều tài khoản, hoặc lịch đăng tự động.

## 3. Giá trị của dự án

- Tự động hóa một quy trình vận hành thực tế có giá trị cao.
- Kết hợp nhiều thành phần phổ biến trong automation: Telegram Bot, `yt-dlp`, Playwright, cookie session, file pipeline.
- Phù hợp để đưa vào portfolio vì thể hiện được tư duy hệ thống, automation workflow và khả năng tích hợp đa dịch vụ.
- Có tiềm năng mở rộng thành nền tảng quản trị nội dung đa kênh.

## 4. Phạm vi MVP

Phiên bản đầu tiên nên tập trung vào một luồng tối thiểu nhưng chạy ổn định:

- Chỉ hỗ trợ 1 Telegram Bot.
- Chỉ hỗ trợ 1 Facebook Fanpage.
- Chỉ xử lý 1 job tại một thời điểm.
- Chỉ nhận 1 link video trong mỗi lệnh.
- Caption nhập thủ công hoặc dùng mẫu mặc định.
- Chạy trên máy local đã đăng nhập Facebook sẵn.

Nếu MVP chạy ổn định, giai đoạn sau mới mở rộng thêm queue, đa page, lịch đăng và dashboard quản trị.

## 5. Luồng hoạt động end-to-end

1. Người dùng gửi link video cho Telegram Bot.
2. Bot chuyển request về ứng dụng Python.
3. Hệ thống tạo một `job` mới và lưu trạng thái ban đầu.
4. Module downloader dùng `yt-dlp` tải video về thư mục tạm.
5. Hệ thống kiểm tra file tải xong, dung lượng và định dạng.
6. Module publisher khởi chạy Playwright với profile/cookie Facebook có sẵn.
7. Bot truy cập đúng Fanpage, mở giao diện tạo bài đăng video.
8. Hệ thống upload video, điền caption, bấm Publish.
9. Module monitor chờ trạng thái hoàn tất hoặc phát hiện lỗi.
10. Kết quả cuối cùng được gửi lại về Telegram Bot và ghi vào log.

## 6. Kiến trúc đề xuất

### Thành phần chính

- `Telegram Bot Client`: nhận lệnh từ người dùng.
- `Command Handler`: phân tích input, validate link, tạo job.
- `Download Service`: tải video bằng `yt-dlp`.
- `Job Manager`: quản lý vòng đời job và trạng thái xử lý.
- `Playwright Publisher`: điều khiển trình duyệt và đăng bài.
- `Session Manager`: quản lý cookie, user data dir, trạng thái đăng nhập.
- `Storage Layer`: lưu file tạm, log, screenshot lỗi, metadata job.
- `Notifier`: gửi phản hồi về Telegram.

### Kiến trúc dữ liệu tối thiểu

Mỗi job nên có các trường:

- `job_id`
- `source_url`
- `caption`
- `status`
- `download_path`
- `created_at`
- `updated_at`
- `error_message`
- `facebook_post_url` hoặc `post_id` nếu lấy được

### Trạng thái job đề xuất

- `queued`
- `downloading`
- `downloaded`
- `publishing`
- `published`
- `failed`
- `retrying`

## 7. Cấu trúc thư mục đề xuất

```text
page_automation/
├─ README.md
├─ requirements.txt
├─ .env.example
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ bot/
│  │  ├─ telegram_bot.py
│  │  └─ handlers.py
│  ├─ services/
│  │  ├─ downloader.py
│  │  ├─ publisher.py
│  │  ├─ job_manager.py
│  │  └─ notifier.py
│  ├─ core/
│  │  ├─ logger.py
│  │  ├─ exceptions.py
│  │  └─ utils.py
│  └─ models/
│     └─ job.py
├─ data/
│  ├─ downloads/
│  ├─ screenshots/
│  └─ sessions/
├─ logs/
└─ tests/
   ├─ test_downloader.py
   ├─ test_job_manager.py
   └─ test_publish_flow.py
```

## 8. Kế hoạch xây dựng cụ thể

### Giai đoạn 1: Khởi tạo môi trường và bộ khung dự án

### Mục tiêu

Tạo bộ khung code có thể chạy được, quản lý cấu hình rõ ràng và sẵn sàng cho từng module sau này.

### Việc cần làm

- Tạo `venv` và cài thư viện nền:
  - `python-telegram-bot` hoặc `aiogram`
  - `playwright`
  - `yt-dlp`
  - `python-dotenv`
  - `pydantic` hoặc `pydantic-settings`
  - `loguru` hoặc logging chuẩn
- Tạo cấu trúc thư mục theo đề xuất.
- Tạo `.env.example` chứa:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_ALLOWED_USER_IDS`
  - `FACEBOOK_PAGE_URL`
  - `PLAYWRIGHT_HEADLESS`
  - `DOWNLOAD_DIR`
  - `SESSION_DIR`
- Tạo `config.py` để đọc biến môi trường.
- Tạo logger dùng chung.
- Tạo `main.py` để khởi động bot hoặc server.

### Kết quả đầu ra

- Dự án chạy được lệnh khởi động cơ bản.
- Có cấu trúc thư mục chuẩn.
- Có file cấu hình mẫu.

### Giai đoạn 2: Xây module nhận lệnh từ Telegram

### Mục tiêu

Cho phép bot nhận link video và xác thực người gửi.

### Việc cần làm

- Tạo bot Telegram.
- Cài đặt các command cơ bản:
  - `/start`
  - `/help`
  - `/publish <url>`
- Kiểm tra user có nằm trong danh sách cho phép hay không.
- Validate URL đầu vào.
- Cho phép gửi kèm caption:
  - ví dụ: `/publish <url> | Caption ở đây`
- Trả phản hồi ngay sau khi tạo job:
  - Job ID
  - Trạng thái ban đầu

### Kết quả đầu ra

- Bot nhận lệnh ổn định.
- Có thể tạo job mới từ Telegram.

### Giai đoạn 3: Xây module tải video bằng yt-dlp

### Mục tiêu

Biến link đầu vào thành file video cục bộ sẵn sàng để upload.

### Việc cần làm

- Viết `downloader.py`.
- Dùng `yt-dlp` với output template rõ ràng.
- Chuẩn hóa tên file.
- Kiểm tra lỗi phổ biến:
  - Link không hợp lệ
  - Video bị chặn
  - Video yêu cầu đăng nhập
  - Lỗi timeout mạng
- Trả về thông tin:
  - đường dẫn file
  - tên file
  - thời lượng nếu lấy được
  - kích thước file
- Log đầy đủ tiến trình download.

### Kết quả đầu ra

- Có thể tải được ít nhất một số nguồn video phổ biến.
- Có dữ liệu đầu vào chuẩn cho module publisher.

### Giai đoạn 4: Thiết lập phiên Facebook và Playwright

### Mục tiêu

Tạo môi trường browser automation ổn định để dùng lại trong nhiều phiên chạy.

### Việc cần làm

- Cài `playwright install`.
- Chọn chiến lược session:
  - Dùng `storage_state.json`, hoặc
  - Dùng `user_data_dir` để giữ phiên đăng nhập
- Tạo script đăng nhập thủ công lần đầu.
- Lưu session vào thư mục `data/sessions/`.
- Viết code mở browser với session có sẵn.
- Kiểm tra khả năng truy cập đúng Fanpage.
- Xử lý timeout, điều hướng chậm, popup bất ngờ.

### Kết quả đầu ra

- Browser mở đúng phiên Facebook đã đăng nhập.
- Có thể vào đúng trang Fanpage mục tiêu.

### Giai đoạn 5: Xây module tự động đăng video

### Mục tiêu

Tự động hoàn tất thao tác upload và publish video lên Fanpage.

### Việc cần làm

- Viết `publisher.py`.
- Xác định selector ổn định cho các bước:
  - nút tạo bài viết
  - khu vực upload video
  - ô nhập caption
  - nút đăng bài
- Upload file bằng Playwright.
- Chờ tiến trình upload hoàn tất.
- Điền caption.
- Bấm publish.
- Xác minh kết quả bằng dấu hiệu thành công:
  - toast thành công
  - redirect
  - post xuất hiện trên page
- Chụp screenshot khi lỗi.

### Kết quả đầu ra

- Có thể publish 1 video hoàn chỉnh từ file local.

### Giai đoạn 6: Orchestrator và quản lý trạng thái job

### Mục tiêu

Kết nối các module rời rạc thành một pipeline hoàn chỉnh.

### Việc cần làm

- Viết `job_manager.py`.
- Xây flow:
  - tạo job
  - download
  - publish
  - notify
- Cập nhật trạng thái sau mỗi bước.
- Retry tối đa 2 đến 3 lần ở bước phù hợp.
- Ghi log theo `job_id`.
- Tách rõ lỗi recoverable và non-recoverable.

### Kết quả đầu ra

- Một lệnh Telegram có thể chạy hết pipeline từ đầu đến cuối.

### Giai đoạn 7: Hoàn thiện tính ổn định và quan sát hệ thống

### Mục tiêu

Làm hệ thống đủ ổn định để dùng thực tế, không chỉ demo.

### Việc cần làm

- Thêm timeout cho từng bước.
- Thêm screenshot và HTML dump khi lỗi Playwright.
- Tạo log file theo ngày.
- Tạo thư mục lưu metadata job.
- Dọn file tạm sau khi publish thành công.
- Thêm cảnh báo khi session Facebook hết hạn.
- Thêm command Telegram:
  - `/status <job_id>`
  - `/last`
  - `/retry <job_id>`

### Kết quả đầu ra

- Hệ thống có khả năng theo dõi và xử lý lỗi thực dụng hơn.

### Giai đoạn 8: Kiểm thử, đóng gói và vận hành

### Mục tiêu

Đưa dự án từ mức chạy được sang mức có thể duy trì và mở rộng.

### Việc cần làm

- Viết test cho logic không phụ thuộc UI:
  - validate input
  - parse command
  - quản lý trạng thái job
- Viết smoke test cho pipeline.
- Tạo `requirements.txt`.
- Tạo script chạy nhanh:
  - `run_bot.bat`
  - `setup_env.bat`
- Viết tài liệu setup.
- Chuẩn bị phương án chạy nền bằng Task Scheduler hoặc service.

### Kết quả đầu ra

- Có bộ tài liệu và lệnh chạy rõ ràng.
- Dễ bàn giao hoặc triển khai lại.

## 9. Backlog mở rộng sau MVP

- Hỗ trợ nhiều Fanpage.
- Hỗ trợ lịch đăng tự động.
- Hỗ trợ queue nhiều job song song.
- Hỗ trợ sinh caption từ template.
- Tự động lấy thumbnail hoặc hashtag.
- Tạo web dashboard theo dõi job.
- Lưu lịch sử publish vào SQLite hoặc PostgreSQL.
- Hỗ trợ nguồn video từ nhiều nền tảng hơn.
- Thêm bước kiểm duyệt nội dung trước khi publish.

## 10. Rủi ro và lưu ý kỹ thuật

- Giao diện Facebook thay đổi thường xuyên, selector có thể hỏng.
- Phiên đăng nhập có thể hết hạn hoặc yêu cầu xác minh bổ sung.
- Một số nguồn video không tải được ổn định bằng `yt-dlp`.
- Upload file lớn sẽ cần timeout dài và cơ chế retry phù hợp.
- Browser automation cần được viết cẩn thận để giảm flakiness.
- Cần quản lý tốt cookie, session và quyền truy cập máy chạy bot.

## 11. Tiêu chí hoàn thành MVP

Dự án được xem là đạt MVP khi đáp ứng đủ các điều kiện sau:

- Người dùng gửi được link từ Telegram.
- Hệ thống tải được video về local thành công.
- Hệ thống upload được video lên đúng Fanpage.
- Hệ thống publish được bài viết hoàn chỉnh.
- Kết quả được gửi ngược lại về Telegram.
- Log đủ để debug khi có lỗi.

## 12. Tech stack đề xuất

- Ngôn ngữ: Python 3.11+
- Bot client: Telegram Bot API
- Media downloader: `yt-dlp`
- Browser automation: `Playwright`
- Config management: `python-dotenv`
- Logging: `logging` hoặc `loguru`
- Data persistence ban đầu: file system hoặc SQLite

## 13. Lộ trình triển khai thực tế đề xuất

Nếu triển khai theo nhịp nhanh, bạn có thể đi theo timeline sau:

### Tuần 1

- Khởi tạo project
- Cấu hình bot Telegram
- Viết module nhận lệnh
- Viết downloader cơ bản

### Tuần 2

- Thiết lập Playwright
- Lưu session Facebook
- Mở được Fanpage bằng automation
- Thử upload file thủ công bằng script

### Tuần 3

- Hoàn thiện flow publish
- Kết nối toàn bộ pipeline
- Trả kết quả về Telegram

### Tuần 4

- Bổ sung retry, log, screenshot lỗi
- Viết test cơ bản
- Hoàn thiện README và tài liệu vận hành

## 14. Định hướng viết code

- Ưu tiên code dễ debug hơn là tối ưu sớm.
- Tách phần điều khiển Playwright thành hàm nhỏ theo từng thao tác UI.
- Mọi bước quan trọng đều phải có log.
- Không hardcode selector và đường dẫn file lung tung trong nhiều nơi.
- Cấu hình phải đưa về `.env`.
- Mỗi job cần có mã định danh riêng để truy vết.

## 15. Mô tả ngắn gọn dùng cho portfolio

Xây dựng hệ thống tự động hóa xuất bản video lên Facebook Fanpage bằng Python, Telegram Bot, `yt-dlp` và Playwright. Người dùng chỉ cần gửi link video qua Telegram, hệ thống sẽ tự động tải video, mở trình duyệt với phiên Facebook đã đăng nhập sẵn, thực hiện upload, nhập nội dung bài viết và publish hoàn toàn tự động. Dự án thể hiện năng lực thiết kế automation pipeline, điều phối nhiều service và xử lý quy trình RPA trong bài toán vận hành nội dung thực tế.

---

Nếu tiếp tục build ngay từ repo này, thứ tự nên làm tiếp là:

1. Tạo `requirements.txt`
2. Tạo `.env.example`
3. Tạo bộ khung `app/`
4. Viết module `downloader.py` đầu tiên
5. Viết bot Telegram nhận lệnh `/publish`
## Phase 1 Quick Start

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:
   `python -m pip install -r requirements.txt`
3. Install the Playwright browser bundle:
   `python -m playwright install`
4. Create a local `.env` from `.env.example` and fill in the required values.
5. Start the scaffold application:
   `python -m app.main`

## Phase 3 Download Notes

- The local downloader layer lives in `app/services/downloader.py` and wraps `yt-dlp` behind a Python service API.
- Focused downloader verification runs with:
  `python -m pytest -q tests/test_downloader.py`

## Phase 4 Session Notes

- The Facebook session bootstrap layer lives in `app/services/session_manager.py`.
- Use Playwright-based session data under the configured `SESSION_DIR` so browser state stays inside the project workspace.
- Focused session/bootstrap verification runs with:
  `python -m pytest -q tests/test_session_manager.py`

## Phase 5 Publisher Notes

- The Playwright publisher flow now lives in `app/services/publisher.py`.
- `FacebookPublisher` reuses `SessionManager`, groups Facebook publish selectors into one contract, and drives upload, caption, publish, and outcome detection with readiness-based waits.
- Failed publish attempts capture a screenshot in `SCREENSHOT_DIR` plus visible failure signals for later debugging.
- Focused publisher verification runs with:
  `python -m pytest -q tests/test_publisher.py`

## Phase 6 Orchestration Notes

- The end-to-end MVP pipeline now runs through `app/services/orchestrator.py`.
- Final job snapshots are persisted as JSON records by `app/services/job_store.py`.
- Final Telegram success/failure messages are formatted and sent by `app/services/notifier.py`.
- Accepted `/publish` requests still receive an immediate queued reply, then hand the job to the orchestrator in the background.
- Focused orchestration verification runs with:
  `python -m pytest -q tests/test_orchestrator.py tests/test_job_store.py tests/test_notifier.py`

## Docker

### Chay bot bang Docker

1. Chuan bi `.env` tu `.env.example`.
2. Build va chay bot:

```bash
docker compose up -d --build
```

3. Xem log:

```bash
docker compose logs -f bot
```

4. Dung bot:

```bash
docker compose down
```

### Luu y ve session trinh duyet

- Container mount `./data` va `./logs`, nen Playwright session nam trong `data/sessions`.
- Container chay mac dinh voi `PLAYWRIGHT_HEADLESS=true`.
- Chromium profile tao tren Windows co the khong portable hoan hao sang Linux container. Neu Business Suite yeu cau dang nhap lai trong Docker, hay bootstrap session lai mot lan trong moi truong container.
