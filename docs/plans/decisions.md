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
| C-04 | Hồ sơ bệnh nhân trên Nano | Mã BN, họ tên, năm sinh, mã lịch thủ thuật trong ngày, embedding; không lưu ảnh mặt trừ ảnh bằng chứng spoof; TTL 24 h | 2026-09-17 | Người dùng |
| C-05 | Môi trường dev | `.venv` + torch CPU; kiểm tra Python 3.6 bằng `vermin` (không chạy pytest trên 3.6) | 2026-09-17 | Người dùng |
| C-06 | Mean/std của 2d106det | mean 0, std 1: graph tự chuẩn hoá, đã kiểm tra trên model gốc | 2026-09-17 | Kiểm chứng (M1) |
| C-07 | Tiền xử lý SCRFD | Letterbox giữ tỉ lệ, pad góc dưới phải; tensor RGB (x−127.5)/128 | 2026-09-17 | Port từ repo tham chiếu (M1) |
| C-08 | Input shape TensorRT | Cố định batch 1: SCRFD 640², 2d106 192², ArcFace 112², MiniFASNet 80² | 2026-09-17 | Plan M1 đã duyệt |
| C-09 | Preview camera cho kiosk | Engine ghi JPEG thu nhỏ vào `/dev/shm/edgeface/preview.jpg` (ghi tạm rồi rename) | 2026-09-17 | Plan DB/UI đã duyệt |
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
| C-19 | Quy trình đo hiệu năng | Trước mỗi lần đo: `sudo jetson_clocks` (không tự áp dụng lại sau reboot). Engine **phải build lúc máy rảnh** — build lúc tải nặng làm TensorRT chọn tactic chậm hơn (ArcFace 18.08 ms so với 14.24 ms) | 2026-09-21 | Đo ở M2/M3 |
| C-15 | D-16 — gộp 2 MiniFASNet | **Không gộp**, giữ 5 engine riêng: cả 5 engine chỉ tốn 1024 MB RSS so với ngân sách 2.0–2.6 GB | 2026-09-21 | Đo ở M2 |

## Mở — pipeline

| Mã | Stage | Câu hỏi | Đề xuất (chưa áp dụng) | Chặn milestone |
|---|---|---|---|---|
| D-01 | S9 | Ngưỡng cosine chấp nhận top1 | Hiệu chuẩn ở M9 từ TAR@FAR=1e-3 trên tập dev | M5 (chạy được với `null`), M9 |
| D-02 | S9 | Khoảng cách tối thiểu top1 − top2 | Hiệu chuẩn ở M9 | M9 |
| D-03 | S9 | Cách gộp điểm khi 1 BN có nhiều template | `max` trên các template | M5 |
| D-04 | S10 | Danh sách enum Decision đầy đủ và bảng luật §6.3 | Xem đề xuất trong `stages/S10_decide.md` | M5 |
| D-05 | S4 | Ngưỡng `p_real ≥ 0.85` áp lên (softmax_V2 + softmax_V1SE) / 2? | Có, như `check_real_face(mode="both")` | M3 |
| D-06 | S2 | Toạ độ vùng ROI | Tỉ lệ theo khung hình, ví dụ `[0.25, 0.1, 0.75, 0.9]`, để đo thực tế | M3 |
| D-07 | S2 | `min_side_px = 110` đo trên ảnh 640×640 hay khung gốc? | Cần chốt; ảnh hưởng khoảng cách đứng | M3 |
| D-08 | S8 | Công thức `quality_score` | Xem các phương án trong `stages/S8_best_frame.md` | M3 |
| D-09 | S6 | Nguồn 5 điểm căn chỉnh: kps SCRFD hay 5 điểm rút từ 106 | Kps SCRFD (khớp cách ArcFace được huấn luyện) | M3 |
| D-10 | S5 | Nội tham số camera cho solvePnP: xấp xỉ (f = chiều rộng ảnh) hay hiệu chuẩn checkerboard | **Ưu tiên cao sau M3**: với f xấp xỉ, ảnh chính diện đo ra pitch −17° và bị gate ±15° loại oan (xem `results/M3_pipeline_perf.md` §3.2). Cần hiệu chuẩn camera kiosk hoặc đo độ lệch nền rồi chốt lại ngưỡng | M9 |
| D-11 | S5 | Định nghĩa vùng tính blur/luminance (crop nào, resize về kích thước nào) | Crop mặt đã căn chỉnh 112×112, ảnh xám | M3 |
| D-15 | S3 | Cách quy đổi tỉ lệ hình học 5 điểm sang độ (yaw) | Công thức trong `stages/S3_coarse_pose.md`, kiểm chứng bằng solvePnP | M3 |
| D-17 | S9 | Cách hiểu luật "3-of-5": ≥ 3 frame bầu cùng một BN, áp dụng cả khi chỉ có 3–4 frame | Như mô tả trong `stages/S9_match.md` §3.2 | M5 |
| D-18 | M9 | FAR mục tiêu để chọn `match.threshold` (1e-3 hay 1e-4); mức tăng FRR tối đa chấp nhận khi thêm margin | FAR 1e-3 | M9 |
| D-31 | S8 | Tính liên tục chủ thể trong cửa sổ thu thập: `iou_min`, `max_gap_s`, có dùng `cos_min` hay không | Cần chốt | M3 |

## Mở — ứng dụng

| Mã | Chủ đề | Câu hỏi | Đề xuất | Chặn milestone |
|---|---|---|---|---|
| D-22 | Lưu trữ | *(phần Nano đã chốt: C-17)* Thời gian giữ embedding và log trên **server** | Cần chốt (liên quan chính sách riêng tư của phòng khám) | M7 |
| D-24 | Sync | Cơ chế ký model bundle | HMAC-SHA256 bằng khoá chung (stdlib) | M7 |
| D-25 | Kiosk | Kích thước và độ phân giải màn hình cảm ứng | Cần chốt | M6 |
| D-26 | Sync | Chu kỳ kéo gallery/revocation | Cần chốt | M7 |
| D-27 | Baseline | LBPH: build OpenCV contrib trên Nano hay tự viết LBPH bằng numpy | Kiểm tra wheel aarch64 trước; nếu không có thì tự viết | M8 |
| D-28 | Dataset | Số người tham gia, số phiên, loại tấn công (PAI), mẫu phiếu đồng ý | Xem `M8_baseline_dataset.md` | M8 |
| D-29 | Server | Tài khoản web quản trị: 1 admin cố định hay nhiều tài khoản | 1 admin + đổi mật khẩu | M7 |
