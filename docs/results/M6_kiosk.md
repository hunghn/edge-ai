# M6 — Kết quả giao diện kiosk

**Ngày:** 2026-09-22 · **Chạy trên:** máy dev (PyQt5 5.15) và Jetson Nano (PyQt5 5.10 từ apt)

Tái lập:
```bash
python3 scripts/db_admin.py create-operator --name "Điều dưỡng A"   # tạo PIN 6 số
python3 scripts/fake_engine.py --config configs/dev.yaml --scenario identify   # cửa sổ 1
python3 -m edgeface.kiosk --config configs/dev.yaml --windowed                 # cửa sổ 2
QT_QPA_PLATFORM=offscreen python tools/viz/kiosk_screens.py                    # chụp ảnh màn hình
```

## 1. Các màn hình
Ảnh trong [`docs/figures/kiosk/`](../figures/kiosk/), chụp ở 1024×600 (màn 7", **D-25 chưa chốt**).

| Ảnh | Màn hình | Ghi chú |
|---|---|---|
| `01_idle.png` | Chờ | "Vui lòng đứng vào khung hình" |
| `02_guidance.png` | Hướng dẫn | preview + chỉ dẫn theo `guidance_code` |
| `03_candidate.png` | Thẻ ứng viên | mã BN, họ tên, năm sinh, mã lịch, mức khớp, đếm ngược, 4 nút |
| `04_spoof.png` | Cảnh báo giả mạo | nền đỏ, **không** hiện thông tin bệnh nhân |
| `05_low_quality.png` | Ảnh không đạt | mời thử lại |
| `06_search.png` | Tìm thủ công | tìm theo mã/tên không dấu |
| `07_pin.png` | Nhập PIN | bàn phím số trên màn hình |
| `08_enroll_progress.png`, `08a_enroll_form.png` | Đăng ký BN | form + tiến độ `k/5` |
| `09_enroll_review.png` | Xem lại trước khi lưu | cảnh báo trùng khuôn mặt |
| `10a-c` | Quản trị / trạng thái / BN hôm nay | |
| `11_camera_error.png` | Lỗi hệ thống | |

## 2. Ba quyết định thiết kế
1. **Không hiện điểm số thô.** Thẻ ứng viên chỉ ghi "Khớp cao" hoặc "Cần kiểm tra". Một con số như 0.81 mời điều dưỡng tranh luận với mô hình, trong khi thang điểm chưa có ý nghĩa cho tới khi hiệu chuẩn ở M9. Có test khoá lại điều này.
2. **Cảnh báo giả mạo không để lộ danh tính.** Nếu ai đó giơ ảnh in của bệnh nhân X, màn hình không được xác nhận hộ họ rằng X có lịch hôm nay.
3. **Lối vào quản trị là cử chỉ ẩn** (giữ góc dưới trái 3 giây, hoặc phím F2 khi có bàn phím), để bệnh nhân không vô tình mở.

## 3. Đo trên Nano
| Chỉ số | Giá trị |
|---|---|
| RAM đỉnh của kiosk | **59 MB** (ngân sách spec: ~250 MB) |
| Test | 237 pass (228 unit + 9 UI offscreen) |
| Qt | 5.10.1 từ apt, không cần build gì thêm |

Kiosk chỉ đọc `kiosk_state` và ghi `kiosk_commands`; nó không nạp model nào, đó là lý do RAM thấp hơn ngân sách nhiều.

## 4. Lỗi thiết kế phát hiện khi làm M6
Trong lúc chờ điều dưỡng (tối đa 30 giây, C-21), engine không ghi gì vào `kiosk_state`, nên kiosk tưởng engine chết sau 5 giây và chuyển sang màn hình lỗi. Đã thêm **nhịp tim**: engine ghi lại trạng thái hiện tại mỗi 0.5 giây, và mốc `timeout_at` tuyệt đối để kiosk tự đếm ngược mà không cần đồng hồ riêng.

## 5. Còn lại
- **D-25:** kích thước/độ phân giải màn hình thật. Hiện dựng theo 1024×600; bố cục co giãn nhưng cần thử trên panel thật.
- **Bàn phím tiếng Việt:** form đăng ký hiện dùng bàn phím vật lý hoặc nhập không dấu (tìm kiếm vẫn đúng nhờ cột `name_search`). Nếu panel không có bàn phím, cần thêm bàn phím ảo — chờ D-25.
- Checklist thao tác tay trên thiết bị thật: chưa chạy, cần màn hình cảm ứng.
