# M6 — Giao diện kiosk (PyQt5, màn hình cảm ứng dùng chung)

**Trạng thái:** ✅ Hoàn thành 2026-09-22 · **Tuần:** 4 · **Phụ thuộc:** M4 · **Cần Nano:** Không

> **Kết quả:** [`docs/results/M6_kiosk.md`](../results/M6_kiosk.md) + ảnh màn hình trong `docs/figures/kiosk/`.
> 237 test pass trên Nano (228 unit + 9 UI offscreen), RAM kiosk **59 MB** so với ngân sách 250 MB.
> Phát hiện: engine không ghi gì trong lúc chờ điều dưỡng nên kiosk tưởng engine chết sau 5 giây → đã thêm nhịp tim 0.5 s và mốc `timeout_at`.
> Khác plan: gộp `widgets/countdown` vào `Page`; bàn phím tiếng Việt hoãn tới khi chốt D-25.

## 1. Mục tiêu và đầu ra
- Tiến trình `kiosk` riêng: `python3 -m edgeface.kiosk --config configs/<env>.yaml`, full-screen, tiếng Việt, RAM ≤ ~250 MB.
- Phục vụ hai nhóm người dùng trên **cùng màn hình** (C-03):
  - **bệnh nhân:** hướng dẫn tư thế
  - **điều dưỡng:** xác nhận, tìm thủ công, quản trị có PIN
- Chỉ đọc `kiosk_state` và ghi `kiosk_commands` qua `storage/kiosk_ipc.py`. Kiosk **không** chạy model và **không** ghi trực tiếp các bảng nghiệp vụ.

## 2. Phạm vi
- **Làm:** các màn hình ở §4, controller, `fake_engine`, systemd unit, smoke test offscreen.
- **Không làm:** web UI (thuộc server M7), đa ngôn ngữ (chỉ chuẩn bị file chuỗi).

## 3. Công nghệ và ràng buộc
- **Trên Nano:** `python3-pyqt5` từ apt (Qt 5.9 trên Ubuntu 18.04). Chỉ dùng Qt Widgets, **không** dùng QML/QtQuick (tốn RAM, GPU đã dành cho TensorRT).
- **Trên máy dev:** `pip install PyQt5`. Code tránh API Qt > 5.9 (ví dụ `QtCore.Qt.ItemFlag` enum mới); smoke test chạy cả hai phiên bản khi có Nano.
- **Poll:** `QTimer` 100 ms gọi `controller.poll()`. Việc đọc DB nhẹ (một dòng), chạy ngay trên main thread; nếu đo thấy giật thì chuyển sang `QThread`.
- **Preview:** `QTimer` theo `kiosk.preview_fps` đọc `/dev/shm/edgeface/preview.jpg` (C-09) → `QImage.fromData` → `QLabel`. Bỏ qua khi file không đổi (`mtime`).
- **Bàn phím:** màn hình cảm ứng không có bàn phím vật lý, nên cần bàn phím số ảo (PIN, năm sinh) và bàn phím chữ ảo có dấu tiếng Việt (tên BN). Đề xuất widget bàn phím tự viết đơn giản (Telex tối giản) hoặc dùng `onboard` của Ubuntu. Quyết khi có thiết bị (D-25).

## 4. Màn hình

| Mã | Màn hình | Hiển thị khi (`kiosk_state.state`) | Thành phần chính | Lệnh gửi |
|---|---|---|---|---|
| UI-01 | Chờ | `IDLE` | Logo/tên phòng khám, "Vui lòng đứng vào khung hình", đồng hồ | – |
| UI-02 | Hướng dẫn | `GUIDING`, `COLLECTING` | Preview + khung ROI; thông điệp lớn theo `guidance_code`: *Đứng gần hơn / Di chuyển vào giữa / Nhìn thẳng vào camera / Giữ yên / Chỗ đứng quá tối / Quá sáng*; thanh tiến độ thu thập | – |
| UI-03 | Thẻ ứng viên | `AWAIT_NURSE` + `decision ∈ {review_required, candidate_suggested}` | Mã BN, họ tên, năm sinh, mã lịch hôm nay; nhãn tin cậy (không hiện điểm số thô); nút **Xác nhận**, **Không phải**, **Thử lại**, **Tìm thủ công**; đếm ngược timeout | `confirm`, `reject`, `retry`, → UI-05 |
| UI-04 | Cảnh báo | `AWAIT_NURSE` + `spoof_suspect` / `low_quality` / `no_match` | Thông điệp + hướng dẫn cho điều dưỡng; `spoof_suspect` có màu cảnh báo và **không** hiện thông tin BN | `retry`, → UI-05 |
| UI-05 | Tìm thủ công | Điều dưỡng mở | Ô tìm (mã/tên không dấu), danh sách BN hôm nay; chọn → xác nhận lần 2 | `manual {code}` |
| UI-06 | Nhập PIN | Nhấn giữ góc màn hình 3 s (cử chỉ ẩn) | Bàn phím số, thông báo khoá sau N lần sai | – (xác thực cục bộ qua `storage/operators.verify`) |
| UI-07 | Quản trị | Sau PIN | Tab: Đăng ký BN · BN hôm nay · Trạng thái hệ thống · Đổi PIN; tự khoá sau D-21 | – |
| UI-08 | Đăng ký BN | Tab của UI-07 | Form: mã BN, họ tên, năm sinh, mã lịch → **Bắt đầu chụp** → preview + tiến độ `k/N` → màn xem lại (cảnh báo trùng nếu có) → **Lưu** / **Huỷ** | `start_enroll`, `enroll_confirm`, `enroll_cancel` |
| UI-09 | BN hôm nay | Tab của UI-07 | Danh sách (mã, tên, nguồn kiosk/server, giờ hết hạn); nút **Thu hồi** (xác nhận 2 lần) | `revoke {code}` |
| UI-10 | Trạng thái hệ thống | Tab của UI-07 | FPS engine, phiên bản gallery + số BN, lần sync cuối, số outbox chờ, dung lượng đĩa, nhiệt độ; lỗi camera | – (đọc DB + `/proc`) |
| UI-11 | Lỗi hệ thống | `CAMERA_ERROR`, `ENGINE_DOWN` (không có cập nhật `kiosk_state` > 5 s) | "Hệ thống tạm dừng, vui lòng gọi nhân viên" | – |

**Riêng tư:**
- UI-03 tự quay về UI-01 ngay sau lệnh hoặc hết timeout.
- Không hiện ảnh gallery (không lưu ảnh, C-04).
- Preview chỉ hiện ở UI-02 và UI-08.

## 5. Kiến trúc mã
```
kiosk/
  __main__.py      # QApplication, full-screen, ẩn con trỏ trên Nano
  controller.py    # KHÔNG import Qt: poll(), current_screen(), actions → kiosk_ipc
  view_model.py    # map kiosk_state → dữ liệu hiển thị (chuỗi, màu, nút bật/tắt)
  strings.py       # mọi chuỗi tiếng Việt, khoá theo guidance_code/decision
  auth.py          # PIN, trạng thái khoá, tự khoá theo thời gian (không import Qt)
  window.py        # QStackedWidget chứa các screen
  screens/{idle,guidance,candidate,alert,manual_search,pin,admin,enroll,patients,status,error}.py
  widgets/{numpad,keyboard_vi,preview,countdown}.py
scripts/fake_engine.py   # phát kịch bản trạng thái vào DB: identify-ok, spoof, low_quality, enroll
```
- `controller` và `view_model` chứa toàn bộ logic, được test bằng pytest thường; `screens/` chỉ dựng widget và nối signal.
- **Phong cách:** chữ lớn (≥ 28 pt cho hướng dẫn), nút ≥ 64 px cho cảm ứng, tương phản cao, màu trạng thái nhất quán (xanh = ok, vàng = cần thao tác, đỏ = cảnh báo). Đặt trong `kiosk/style.qss`.

## 6. Công việc

| Mã | Công việc |
|---|---|
| M6-T01 | `strings.py` + bảng ánh xạ `guidance_code`/`decision` → chuỗi; test đủ khoá |
| M6-T02 | `controller.py`, `view_model.py`, `auth.py` + test |
| M6-T03 | `scripts/fake_engine.py` với các kịch bản YAML trong `tests/fixtures/kiosk_scenarios/` |
| M6-T04 | Khung `window.py` + UI-01, UI-02, UI-11 |
| M6-T05 | UI-03, UI-04, UI-05 |
| M6-T06 | UI-06, UI-07, UI-09, UI-10 |
| M6-T07 | UI-08 (enroll) + các lệnh enroll phía engine đã có ở M5 |
| M6-T08 | Widget bàn phím số/chữ (theo quyết định ở §3) |
| M6-T09 | `deploy/systemd/edgeface-kiosk.service` (chạy trong phiên đồ hoạ, auto-login user kiosk, `Restart=always`) |
| M6-T10 | Smoke test offscreen + đo RAM/CPU |
| M6-T11 | Ảnh chụp các màn hình → `docs/figures/kiosk/` (dùng cho báo cáo) |

## 7. Giá trị cần xác nhận
- **D-21:** timeout `AWAIT_NURSE`, thời gian tự khoá quản trị.
- **D-23:** PIN.
- **D-25:** kích thước/độ phân giải màn hình.
- **Nhãn tin cậy hiển thị:** "khớp cao" / "cần kiểm tra". Có hiện điểm số thô cho điều dưỡng không? Đề xuất **không**.
- **Cử chỉ mở quản trị:** nhấn giữ góc 3 s, hay nút có biểu tượng.
- **Tên hiển thị trên thẻ:** hiện đầy đủ hay che một phần (ví dụ "Nguyễn T. H."). Màn hình có thể bị bệnh nhân khác nhìn thấy.

## 8. Kiểm thử
- **Unit:** controller (mọi `state` → màn hình đúng; lệnh sai phiên bị chặn), auth (khoá sau N lần sai, mở khoá sau thời gian), view_model (chuỗi đúng cho mọi `guidance_code`).
- **Smoke offscreen:** `QT_QPA_PLATFORM=offscreen pytest tests/ui -m ui`, chạy `fake_engine` theo từng kịch bản; assert màn hình hiện hành và lệnh được ghi vào `kiosk_commands`.
- **Thủ công trên Nano** (checklist trong `docs/results/M6_ui_checklist.md`): chạm các nút, bàn phím tiếng Việt, độ trễ từ trạng thái engine đến hiển thị (mục tiêu hiển thị trong 1 chu kỳ poll), RAM ≤ 250 MB, CPU kiosk.

## 9. Tiêu chí hoàn thành
- [ ] Đủ 11 màn hình chạy với `fake_engine`
- [ ] Test unit + smoke pass
- [ ] Chạy trên Nano cùng engine thật; checklist thủ công đạt; RAM/CPU được ghi lại

## 10. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Qt 5.9 thiếu API dùng trên dev | Kiểm tra sớm trên Nano; tránh API mới |
| Bàn phím tiếng Việt trên cảm ứng khó dùng | Cho phép nhập tên không dấu (tìm kiếm vẫn đúng nhờ `name_search`); ưu tiên mã BN |
| Kiosk và engine tranh RAM | Không dùng QML, ảnh preview nhỏ, đo ở M6-T10 |
