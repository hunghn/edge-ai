# M6 — Kết quả giao diện kiosk

**Ngày:** 2026-09-22, vẽ lại theo Material 3 ngày 2026-09-25
**Chạy trên:** máy dev (PyQt5 5.15) và Jetson Nano (PyQt5 5.10 từ apt)

Tái lập:
```bash
python3 scripts/db_admin.py create-operator --name "Điều dưỡng A"   # tạo PIN 6 số
python3 scripts/fake_engine.py --config configs/dev.yaml --scenario identify   # cửa sổ 1
python3 -m edgeface.kiosk --config configs/dev.yaml --windowed                 # cửa sổ 2
QT_QPA_PLATFORM=offscreen python tools/viz/kiosk_screens.py                    # chụp ảnh màn hình
```
Bảy kịch bản: `identify`, `spoof`, `low_quality`, `no_match`, `enroll`, `duplicate`,
`camera_error` (`python3 scripts/fake_engine.py --list`).

## 1. Các màn hình
Ảnh trong [`docs/figures/kiosk/`](../figures/kiosk/), chụp ở 1024×640 (**D-25 chưa chốt**).
Wireframe đã duyệt: https://claude.ai/artifact/BTy8KG6LdVK4FkJDsCL29U

| Ảnh | Màn hình | Ghi chú |
|---|---|---|
| `01_idle.png` | Chờ | lời mời + hai điều kiện chụp; thanh trạng thái camera/đồng bộ |
| `02_guidance.png` | Hướng dẫn | camera bên trái, stepper 5 cửa bên phải, chỉ dẫn nằm **trên** ảnh |
| `03_candidate.png` | Thẻ ứng viên | ảnh đã chọn cạnh hồ sơ; điểm số gom vào thẻ phụ; vòng đếm ngược cạnh nút Xác nhận |
| `04_spoof.png` | Cảnh báo giả mạo | thanh tiêu đề đỏ, ba bước xử lý, **không** hiện thông tin bệnh nhân |
| `05_low_quality.png` | Ảnh không đạt | nêu rõ chỉ số nào trượt và ngưỡng của nó |
| `05b_no_match.png` | Không có trong danh sách | nêu phạm vi tìm kiếm; lối đi thẳng sang Đăng ký mới |
| `06_search.png` | Tìm thủ công | thanh tìm Material, dòng có avatar, bàn phím ảo |
| `07_pin.png` | Nhập PIN | bàn phím số bên phải, ô PIN bên trái |
| `08a_enroll_form.png` | Đăng ký — thông tin | form hai cột + stepper 3 bước + bàn phím ảo |
| `08_enroll_progress.png` | Đăng ký — chụp | 5 ô ảnh và thanh tiến độ |
| `09_enroll_review.png` | Xem lại trước khi lưu | độ đồng nhất, số đặc trưng |
| `09b_duplicate.png` | Trùng khuôn mặt | ảnh đang chụp cạnh ảnh đã có; nút an toàn là nút chính |
| `10a_admin.png` | Quản trị | navigation rail + 4 thẻ có sẵn số liệu |
| `10b_status.png` | Trạng thái hệ thống | 6–8 ô số, mỗi ô kèm câu diễn giải |
| `10c_patients.png` | Bệnh nhân hôm nay | nguồn, số đặc trưng, hạn 24 h, thùng rác mỗi dòng |
| `10d_revoke.png` | Xác nhận thu hồi | dialog chặn ngang, nút xác nhận mang nhãn khác |
| `11_camera_error.png` | Lỗi hệ thống | nói bệnh nhân cần làm gì, kèm mã lỗi |
| `12_change_pin.png` | Đổi PIN | ba bước vẽ rõ ở đầu màn |

## 2. Bốn quyết định thiết kế
1. **Số liệu tách khỏi kết luận.** Thẻ ứng viên đọc "Khớp cao" hoặc "Cần kiểm tra" trước; điểm cosine, khoảng cách tới người thứ hai và người gần nhì nằm trong một thẻ phụ mờ hơn, tắt được bằng `kiosk.show_score`. Thang điểm chưa hiệu chuẩn (M9), nên nó không được đứng ngang hàng với kết luận.
2. **Cảnh báo giả mạo không để lộ danh tính.** Nếu ai đó giơ ảnh in của bệnh nhân X, màn hình không được xác nhận hộ họ rằng X có lịch hôm nay.
3. **Lối vào quản trị là cử chỉ ẩn** (giữ góc dưới trái 3 giây, hoặc F2 khi có bàn phím), để bệnh nhân không vô tình mở.
4. **Việc không hoàn tác được thì hỏi lại bằng dialog.** Thu hồi xoá dữ liệu khuôn mặt khỏi máy; câu hỏi nêu tên bệnh nhân và nút xác nhận mang nhãn khác với nút vừa bấm.

## 3. Đo trên Nano
| Chỉ số | Giá trị |
|---|---|
| RAM đỉnh của kiosk | **59 MB** đo ở bản đầu (ngân sách spec: ~250 MB) — **cần đo lại sau khi vẽ lại** |
| Test | 415 pass (379 unit + 36 UI offscreen) trên máy dev |
| Qt | 5.10.1 từ apt, không cần build gì thêm |

Kiosk chỉ đọc `kiosk_state` và ghi `kiosk_commands`; nó không nạp model nào, đó là lý do RAM thấp hơn ngân sách nhiều. Bản vẽ lại không thêm ảnh hay font nào — biểu tượng vẽ bằng `QPainter` — nên RAM dự kiến không đổi đáng kể, nhưng con số trong bảng vẫn là của bản cũ cho tới khi chạy lại trên thiết bị.

## 4. Lỗi phát hiện khi làm M6
- **Nhịp tim.** Trong lúc chờ điều dưỡng (tối đa 30 giây, C-21), engine không ghi gì vào `kiosk_state`, nên kiosk tưởng engine chết sau 5 giây. Đã thêm nhịp tim 0.5 giây và mốc `timeout_at` tuyệt đối.
- **Bàn phím ảo cướp focus.** Phím bấm nhận focus sẽ lấy focus khỏi ô đang gõ, nên từ chữ thứ hai trở đi mọi ký tự rơi vào ô đầu tiên. Phím nay đặt `Qt.NoFocus`.
- **`deleteLater` không gỡ widget khỏi màn hình ngay.** Thanh nút và bàn phím vẽ chồng widget cũ lên widget mới cho tới khi vòng lặp sự kiện dọn. Mọi chỗ dựng lại nay dùng `components.clear_layout()` (ẩn → gỡ cha → xoá).
- **Timer sống lâu hơn cửa sổ.** `window.close()` không dừng timer 100 ms, timer tiếp tục gọi controller có kết nối SQLite đã đóng; trong Qt đó là abort chứ không phải traceback. Đã thêm `closeEvent`.
- **QSS không tô nền `QWidget` thuần.** Qt chỉ tô khi widget được bật `WA_StyledBackground`, nên thanh tiêu đề, rail, bàn phím và lớp phủ dialog đều mất nền.

## 5. Còn lại
- **D-25:** kích thước/độ phân giải màn hình thật. Hiện dựng theo 1024×640; cần thử trên panel thật và đo lại RAM/CPU.
- **Bàn phím tiếng Việt:** đã có bàn phím ảo **không dấu** (đủ cho tìm kiếm vì `name_search` đã bỏ dấu, và mã BN là ASCII). Telex chờ D-25.
- **`kiosk.support_phone`** đang để trống: khối "Gọi kỹ thuật" ở màn lỗi chỉ hiện khi có số thật.
- **D-33** (ngưỡng cảnh báo người gần nhì) chưa hiệu chuẩn, nên hàng "Người gần nhì" vẫn chỉ là thông tin.
- Checklist thao tác tay trên thiết bị thật: chưa chạy, cần màn hình cảm ứng.
