# S0 — Thu khung hình (capture)

**Milestone:** M3 (task M3-T10) · **Module:** `src/edgeface/pipeline/capture.py`

## 1. Mục tiêu
Cung cấp **khung hình mới nhất** cho engine với tốc độ 10–15 FPS, độ trễ thấp, không tích luỹ hàng đợi. Thread capture chạy trong tiến trình engine.

## 2. Input / Output
- **Input:** webcam USB qua `v4l2src` + MJPG (Nano, chốt C-12); trên máy dev là file video hoặc webcam USB.
- **Output:** `Frame(frame_id, ts, image)`. `image` là HxWx3 uint8 BGR ở 1920×1080 (chốt C-13); `ts = time.monotonic()` lúc nhận frame.
- Ảnh 640×640 cho detector **không** tạo ở S0; S1 tự letterbox từ khung đầy đủ để S4/S5 dùng được ảnh gốc.

## 3. Thiết kế
```
FrameSource (interface)
 ├─ GStreamerSource(pipeline_str)      # cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
 ├─ FileSource(path, realtime, loop)   # cv2.VideoCapture(path)
 └─ UsbSource(index, width, height)    # dev
CaptureThread(source, ring)            # threading.Thread(daemon=True)
RingBuffer                             # 1 slot + Condition: put() ghi đè, get_latest(after_id, timeout)
```
- `RingBuffer.get_latest(after_id)` chỉ trả frame có `frame_id > after_id`, nên engine không xử lý lại cùng một frame. Frame cũ bị ghi đè (drop) và số frame bị drop được đếm.
- Pipeline GStreamer mặc định (trong `configs/nano.yaml`):
  `v4l2src device=/dev/video0 io-mode=2 ! image/jpeg,width=1920,height=1080,framerate=30/1 ! jpegdec ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1`
  Pipeline cho camera CSI (`nvarguscamerasrc`) giữ lại dạng comment trong cùng file, phòng khi đổi phần cứng.
- **Giới hạn FPS:** camera khai báo 30 FPS nhưng đo thực chỉ đạt ~14.9 FPS (giải mã MJPG trên CPU); engine tự xử lý ở tốc độ tối đa. `capture.fps` chỉ dùng cho `FileSource` realtime, không bóp camera.
- **Tự kết nối lại:** nếu `read()` fail N lần liên tiếp thì đóng và mở lại sau `reconnect_s` giây, ghi log `camera_lost`. Engine báo `CAMERA_ERROR` cho kiosk (M5).
- **Tắt an toàn:** `stop()` đặt cờ, `join(timeout)`, `release()`.
- **Camera treo:** với USB thì rút/cắm lại hoặc `usbreset`; nếu sau này dùng CSI thì `sudo systemctl restart nvargus-daemon`.

## 4. Config keys
`capture.source` (`gstreamer|file|usb`), `capture.pipeline`, `capture.path`, `capture.usb_index`, `capture.width`, `capture.height`, `capture.fps` (file realtime), `capture.read_fail_max`, `capture.reconnect_s`.

## 5. Giá trị cần xác nhận
- ~~D-12~~ → **chốt C-13: giữ 1080p**. Đo trên máy: MJPG cho 14.9 FPS ở cả 1080p và 720p, YUYV chỉ 9.1 FPS.
- ~~D-13~~ → **chốt C-12: webcam USB** "UGREEN Camera 2K" trên `/dev/video0`, dùng `v4l2src` + MJPG (pipeline CSI giữ dạng comment trong `configs/nano.yaml`).
- `read_fail_max`, `reconnect_s`: giá trị vận hành. Đề xuất 30 frame / 2 s, chờ duyệt.

## 6. File
- `src/edgeface/pipeline/capture.py`
- `tests/unit/test_ring_buffer.py`, `tests/unit/test_capture_file.py`
- `scripts/camera_check.py`: mở camera, in FPS thực, lưu 1 ảnh (dùng ở M2/M3)

## 7. Trường hợp biên
- Video file hết thì `FileSource` báo `eof`; runner offline dừng sạch.
- Engine xử lý chậm hơn camera: frame bị drop, không tăng độ trễ (kiểm tra bằng test).
- Camera bị rút giữa chừng: có log, tự kết nối lại, không crash engine.
- Không mở được pipeline GStreamer (máy dev): factory báo lỗi rõ ràng, gợi ý dùng `dev.yaml`.

## 8. Test
- `RingBuffer`: 1 producer 100 FPS + 1 consumer chậm, kiểm tra consumer luôn nhận frame mới nhất, `frame_id` tăng dần, đếm drop đúng.
- `get_latest(timeout)` trả `None` khi không có frame mới.
- `FileSource` với video tổng hợp (tạo bằng `cv2.VideoWriter` trong test): đọc đủ frame, `realtime=True` giữ đúng nhịp ±10%.

## 9. Đo lường
FPS nhận từ camera, FPS engine xử lý, số frame drop/phút, độ trễ `now − frame.ts` khi bắt đầu S1 (p50/p95), CPU% của thread capture.

## 10. Tiêu chí hoàn thành
- [ ] Test unit pass; chạy `camera_check.py` trên Nano đạt ≥ 15 FPS nhận (đo sơ bộ bằng OpenCV: 14.9 FPS)
- [ ] Độ trễ capture→S1 p95 được ghi vào `docs/results/M3_pipeline_perf.md`
- [x] D-12/D-13 đã chốt (C-12, C-13)
