# Sổ quyết định (Decision Register)

Nơi ghi mọi giá trị hoặc lựa chọn mà spec không nêu, hoặc cần người dùng chốt. **Không được tự đặt giá trị trong code** khi mục tương ứng còn *Mở*. Trong lúc chờ, config để `null` hoặc dùng giá trị "đề xuất" có ghi chú `TBD`.

Cách cập nhật: khi đã chốt, chuyển mục sang bảng "Đã chốt" và ghi ngày, người chốt, giá trị cuối cùng.

## Đã chốt

| Mã | Nội dung | Giá trị chốt | Ngày | Nguồn |
|---|---|---|---|---|
| C-12 | Camera thực tế (D-13 cũ) | Webcam USB "UGREEN Camera 2K" trên `/dev/video0`, dùng MJPG (YUYV chỉ 9 FPS). `configs/nano.yaml` đã đổi sang `v4l2src`; pipeline CSI giữ lại dạng comment | 2026-09-21 | Đo trên máy |
| C-01 | Nơi đăng ký khuôn mặt (enrollment) | Ngay trên kiosk Nano, chạy được offline | 2026-09-17 | Người dùng |
| C-02 | Server | Server tối giản tự viết: FastAPI + SQLite, chạy trên PC/laptop, có API sync và web quản trị | 2026-09-17 | Người dùng |
| C-03 | Giao diện điều dưỡng | Cùng màn hình cảm ứng kiosk (PyQt5), phần quản trị khoá bằng PIN | 2026-09-17 | Người dùng |
| C-04 | Hồ sơ bệnh nhân trên Nano | Mã BN, họ tên, năm sinh, mã lịch thủ thuật trong ngày, embedding; không lưu ảnh mặt trừ ảnh bằng chứng spoof; TTL 24 h. **Đã sửa bởi C-24**: thêm 1 crop mặt cho mỗi BN đăng ký tại kiosk, phục vụ cảnh báo trùng | 2026-09-17 | Người dùng |
| C-05 | Môi trường dev | `.venv` + torch CPU; kiểm tra Python 3.6 bằng `vermin` (không chạy pytest trên 3.6) | 2026-09-17 | Người dùng |
| C-06 | Mean/std của 2d106det | mean 0, std 1: graph tự chuẩn hoá, đã kiểm tra trên model gốc | 2026-09-17 | Kiểm chứng (M1) |
| C-07 | Tiền xử lý SCRFD | Letterbox giữ tỉ lệ, pad góc dưới phải; tensor RGB (x−127.5)/128 | 2026-09-17 | Port từ repo tham chiếu (M1) |
| C-08 | Input shape TensorRT | Cố định batch 1: SCRFD 640², 2d106 192², ArcFace 112², MiniFASNet 80² | 2026-09-17 | Plan M1 đã duyệt |
| C-09 | Preview camera cho kiosk | **Ảnh thô RGB ở độ phân giải gốc của camera (1920×1080)** trong `/dev/shm/edgeface/preview.rgb` (header 8 byte `EFP1`+w+h, `common/preview_frame.py`), ghi tạm rồi rename, **ở luồng riêng của engine** (`PreviewWriter`) để vòng S1–S10 không phải chờ; 15 FPS. Thay cho JPEG 480 px q70 (bị phóng 3.4× lên khung 1612 px của màn 3200×2000 nên mờ). Đo trên Nano/khung: JPEG 1920 q85 nén 37 ms + giải nén 32 ms trên luồng UI kiosk; thô ghi 22 ms + kiosk dựng ≈10 ms. `kiosk.preview_format: jpeg` vẫn dùng được. Camera không lên 2304 px được: mức đó chỉ có ở YUYV, qua USB 2.0 YUYV chỉ đạt 9 FPS ở 1080p | 2026-10-08 (thay bản 2026-09-17) | Người dùng |
| C-10 | Môi trường Nano thực tế | JetPack 4.6 / Python 3.6.9 / TensorRT 8.2.1.8 / numpy 1.13.3 / OpenCV 4.1.1 **không CUDA**, có GStreamer 1.14.5 / SQLite 3.22.0 / swap chỉ có zram 4×494 MB | 2026-09-21 | Kiểm kê thiết bị (M2-T01) |
| C-11 | MiniFASNet trên TensorRT | `BatchNormalization` 1 chiều parse được bình thường, **không cần** `fold_bn1d.py` | 2026-09-21 | 5 engine build OK trên máy |
| C-13 | D-12 — độ phân giải ring buffer | **Giữ 1080p** (camera cho 14.9 FPS ở cả 1080p và 720p) | 2026-09-21 | Người dùng |
| C-14 | Đo công suất | Cho phép `sudo` không mật khẩu **chỉ với `/usr/bin/tegrastats`** (`/etc/sudoers.d/edgeface-tegrastats`); dùng `bench_model.py --tegrastats --tegrastats-sudo`. Không có quyền root nào khác được mở | 2026-09-21 | Người dùng |
| C-16 | D-14 — ảnh bằng chứng spoof | Lưu **crop mặt** (scale 4.0) dạng JPEG, TTL **7 ngày** | 2026-09-21 | Người dùng |
| C-17 | D-22 (phần Nano) — nhật ký phiên | Giữ **30 ngày** trên Nano (không chứa ảnh); thời gian giữ embedding trên server vẫn mở | 2026-09-21 | Người dùng |
| C-18 | D-23 — chính sách PIN | **6 chữ số**, sai **5 lần** thì khoá **5 phút**; hash PBKDF2-HMAC-SHA256 | 2026-09-21 | Người dùng |
| C-20 | D-30 — luật spoof cấp phiên | **≥ 2 frame** bị S4 chặn trong cửa sổ thu thập thì kết luận `spoof_suspect` (`decision.spoof_min_frames`) | 2026-09-22 | Người dùng |
| C-21 | D-21 — mốc thời gian phiên | Chờ điều dưỡng **30 s**, nghỉ giữa hai lượt **3 s**, màn quản trị tự khoá sau **60 s** | 2026-09-22 | Người dùng |
| C-22 | D-20 — enrollment | **Tự động chụp 5 mẫu**; nếu trùng khuôn mặt với BN khác thì **cảnh báo rồi vẫn cho lưu** sau khi điều dưỡng xác nhận lần hai | 2026-09-22 | Người dùng |
| C-23 | D-27 — nguồn LBPH | **Tự viết bằng numpy** (`baselines/haar_lbph/lbph.py`). Nano không có `cv2.face`, pip không có wheel aarch64/py3.6 (chỉ có mã nguồn 154 MB của OpenCV 5). Có 10 test đối chứng với `cv2.face` trên máy dev | 2026-09-22 | Kiểm chứng ở M8 |
| C-24 | Ảnh khuôn mặt bệnh nhân (đảo một phần **C-04**) | Lưu **1 crop 112×112 đã căn chỉnh** cho mỗi BN đăng ký tại kiosk, dạng BLOB trong bảng `patient_faces`, TTL bằng TTL bệnh nhân (24 h, xoá theo `ON DELETE CASCADE`). **Không bao giờ** vào outbox — server không nhận ảnh. Chỉ dùng cho màn cảnh báo trùng mặt. Lý do: embedding không dựng ngược thành ảnh, mà điều dưỡng cần thấy mặt mới phân biệt được "cùng người đăng ký hai lần" với "hai người giống nhau" | 2026-09-24 | Người dùng |
| C-19 | Quy trình đo hiệu năng | Trước mỗi lần đo: `sudo jetson_clocks` (không tự áp dụng lại sau reboot). Engine **phải build lúc máy rảnh** — build lúc tải nặng làm TensorRT chọn tactic chậm hơn (ArcFace 18.08 ms so với 14.24 ms) | 2026-09-21 | Đo ở M2/M3 |
| C-15 | D-16 — gộp 2 MiniFASNet | **Không gộp**, giữ 5 engine riêng: cả 5 engine chỉ tốn 1024 MB RSS so với ngân sách 2.0–2.6 GB | 2026-09-21 | Đo ở M2 |
| C-25 | D-10 — gate tư thế S5 | **Bỏ gate bằng góc solvePnP, gate bằng tỉ lệ khoảng cách trên 106 landmark của ims_id_server** (`tools/tools.py::face_analysis`, đã chạy ổn định thực tế), giữ nguyên ngưỡng của reference: UD = ‖72−86‖/‖0−86‖ trong (0.20, 0.85); RL = ‖12−86‖/‖28−86‖ trong [0.5, 2.2]; mắt nhắm khi eye_rate ≤ 0.12; miệng mở khi mouth_rate ≥ 0.20; roll (đường nối 2 mắt) vẫn ±10° theo spec. Lý do: solvePnP với mô hình 3D chung + f xấp xỉ đo mặt chính diện ra pitch −8° … −22° (6 ảnh/video), làm S5 chặn 100% frame, nên cả đăng ký lẫn nhận diện không chạy được. Mặt chính diện đo được UD 0.47–0.55, RL 0.74–1.01, eye 0.21–0.27, mouth ≤ 0.17. solvePnP vẫn tính để hiển thị; `pose_fine.method: pnp` giữ lại cho M9 so sánh | 2026-10-08 | Người dùng |
| C-26 | D-01, D-02, D-04 (một phần) — ngưỡng S9 và kết quả "Khớp cao" | **`match.threshold` = 0.80** mặc định; **`match.margin_top1_top2` = không xét** (null). Cả hai **chỉnh được trên kiosk** (Quản trị → Cài đặt nhận diện, sau PIN) trong khoảng `admin_settings`: ngưỡng 0.50–0.95 bước 0.05; margin trống hoặc 0.05–0.30 bước 0.05. Giá trị chỉnh lưu trong `gallery_meta` (`storage/settings.py`), engine đọc lại ở mỗi lần quyết định, mỗi lần đổi đẩy event `settings.changed` (ai đổi, cũ → mới) lên server. Bật outcome `candidate_suggested` (R5); y tá vẫn luôn phải xác nhận. Lý do: bn02 đúng người đạt 0.86–0.90 trên Nano nhưng luôn bị báo "Cần kiểm tra". M9 vẫn hiệu chuẩn lại từ TAR@FAR (chưa có số đo impostor trên thiết bị) | 2026-10-08 | Người dùng |

## Mở — pipeline

| Mã | Stage | Câu hỏi | Đề xuất (chưa áp dụng) | Chặn milestone |
|---|---|---|---|---|
| D-03 | S9 | Cách gộp điểm khi 1 BN có nhiều template | `max` trên các template | M5 |
| D-04 | S10 | Danh sách enum Decision đầy đủ và bảng luật §6.3 | Xem đề xuất trong `stages/S10_decide.md` (2026-10-08: đã bật `candidate_suggested`, xem C-26; `no_match` và `no_match_below` vẫn mở) | M5 |
| D-05 | S4 | Ngưỡng `p_real ≥ 0.85` áp lên (softmax_V2 + softmax_V1SE) / 2? | Có, như `check_real_face(mode="both")` | M3 |
| D-06 | S2 | Toạ độ vùng ROI | Tỉ lệ theo khung hình, ví dụ `[0.25, 0.1, 0.75, 0.9]`, để đo thực tế | M3 |
| D-07 | S2 | `min_side_px = 110` đo trên ảnh 640×640 hay khung gốc? | Cần chốt; ảnh hưởng khoảng cách đứng | M3 |
| D-08 | S8 | Công thức `quality_score` | Xem các phương án trong `stages/S8_best_frame.md`. Lưu ý (C-25): pitch solvePnP còn lệch ~−20° trên mặt thẳng, nên số hạng pitch trong công thức sẽ phạt oan mọi frame; cần đổi sang tỉ lệ UD trước khi bật | M3 |
| D-09 | S6 | Nguồn 5 điểm căn chỉnh: kps SCRFD hay 5 điểm rút từ 106 | Kps SCRFD (khớp cách ArcFace được huấn luyện) | M3 |
| D-11 | S5 | Định nghĩa vùng tính blur/luminance (crop nào, resize về kích thước nào) | Crop mặt đã căn chỉnh 112×112, ảnh xám | M3 |
| D-15 | S3 | Cách quy đổi tỉ lệ hình học 5 điểm sang độ (yaw) | Công thức trong `stages/S3_coarse_pose.md`, kiểm chứng bằng solvePnP | M3 |
| D-17 | S9 | Cách hiểu luật "3-of-5": ≥ 3 frame bầu cùng một BN, áp dụng cả khi chỉ có 3–4 frame | Như mô tả trong `stages/S9_match.md` §3.2 | M5 |
| D-18 | M9 | FAR mục tiêu để chọn `match.threshold` (1e-3 hay 1e-4); mức tăng FRR tối đa chấp nhận khi thêm margin | FAR 1e-3 | M9 |
| D-31 | S8 | Tính liên tục chủ thể trong cửa sổ thu thập: `iou_min`, `max_gap_s`, có dùng `cos_min` hay không | Cần chốt | M3 |
| D-32 | Enroll | `enroll.duplicate_show_min` — dưới điểm này thì một BN chỉ là "gần nhất", không phải "giống". Trong lúc `null`, màn cảnh báo liệt kê tối đa 3 người gần nhất và ghi rõ ngưỡng chưa hiệu chuẩn | Hiệu chuẩn cùng D-01 ở M9 | M9 |
| D-33 | S10 | `decision.lookalike_margin` — khoảng cách top1−top2 nhỏ tới mức nào thì cảnh báo "hai người giống nhau" lúc nhận diện. Hiện người gần nhì chỉ hiện dạng thông tin tham khảo | Hiệu chuẩn cùng D-02 ở M9 | M9 |

## Mở — ứng dụng

| Mã | Chủ đề | Câu hỏi | Đề xuất | Chặn milestone |
|---|---|---|---|---|
| D-22 | Lưu trữ | *(phần Nano đã chốt: C-17)* Thời gian giữ embedding và log trên **server** | Cần chốt (liên quan chính sách riêng tư của phòng khám) | M7 |
| D-24 | Sync | Cơ chế ký model bundle | HMAC-SHA256 bằng khoá chung (stdlib) | M7 |
| D-25 | Kiosk | Kích thước và độ phân giải màn hình cảm ứng | Cần chốt | M6 |
| D-26 | Sync | Chu kỳ kéo gallery/revocation | Cần chốt | M7 |
| D-28 | Dataset | Số người tham gia, số phiên, loại tấn công (PAI), mẫu phiếu đồng ý | Xem `M8_baseline_dataset.md` | M8 |
| D-29 | Server | Tài khoản web quản trị: 1 admin cố định hay nhiều tài khoản | 1 admin + đổi mật khẩu | M7 |
