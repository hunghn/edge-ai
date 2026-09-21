# S2 — Chọn chủ thể (ROI geometry)

**Milestone:** M3 (task M3-T12) · **Module:** `src/edgeface/pipeline/subject.py`

## 1. Mục tiêu
Từ danh sách mặt của S1, chọn **một** người đang đứng trước kiosk: bbox lớn nhất, tâm nằm trong ROI, cạnh ≥ 110 px. Nếu không đạt, hướng dẫn "đứng gần hơn" hoặc "vào giữa khung".

## 2. Input / Output
- **Input:** `[Detection]` từ S1, kích thước khung (W, H).
- **Output (ok):** `StageResult(True, None, Detection)`.
- **Output (fail):** `StageResult(False, reason, Detection|None)`, với `reason ∈ {STEP_CLOSER, MOVE_TO_CENTER}`.

## 3. Thuật toán
1. `roi_px = roi_frac × [W, H, W, H]`. ROI khai báo theo **tỉ lệ khung** để không phụ thuộc độ phân giải (D-06).
2. Chọn `cand = argmax(area(bbox))` trên **toàn bộ** mặt. Spec ghi "largest bbox"; chọn trước khi lọc ROI để khi người gần nhất đứng lệch thì hướng dẫn họ vào giữa, thay vì bắt nhầm người phía sau.
3. Nếu `center(cand)` ∉ ROI → `MOVE_TO_CENTER`.
4. Nếu `min_side(cand)` < `min_side_px` (theo hệ toạ độ D-07) → `STEP_CLOSER`.
5. Ngược lại → ok.

Quy đổi hệ toạ độ cho `min_side_px`:
- Nếu D-07 chốt "đo trên ảnh 640": `side_det = side_frame × letterbox_scale`, với `letterbox_scale = 640 / max(W, H)`.
- Nếu chốt "đo trên khung gốc": dùng trực tiếp.

Hàm dùng từ M1: `common/geometry.py::bbox_area, bbox_center, bbox_min_side, point_in_rect`.

## 4. Config keys
`subject.roi` ([x1, y1, x2, y2], tỉ lệ 0–1), `subject.min_side_px` (110), `subject.min_side_space` (`det|frame`).

## 5. Giá trị cần xác nhận
- **D-06:** toạ độ ROI. Đang `null`; khi `null`, stage coi ROI = toàn khung và ghi cảnh báo một lần.
- **D-07:** hệ toạ độ của 110 px. Cùng một số 110 nhưng khác nhau ~3 lần giữa 640 và 1920, nên khoảng cách đứng tối đa thay đổi đáng kể.
- **Chính sách nhiều người trong ROI:** spec chọn mặt lớn nhất. Có cần thêm cảnh báo "chỉ một người" khi mặt lớn thứ hai cũng ≥ `min_side_px` không? Mặc định **không** (theo spec); ghi chú để chốt cùng D-06.

## 6. File
- `src/edgeface/pipeline/subject.py`
- `tests/unit/test_subject.py`

## 7. Trường hợp biên
- Hai mặt diện tích bằng nhau: chọn mặt có score cao hơn (xác định, có test).
- bbox âm hoặc vượt khung: tâm vẫn tính bình thường; diện tích dùng `max(0, ...)`.
- ROI không hợp lệ (x1 ≥ x2): `config.validate` báo lỗi khi nạp.

## 8. Test
- Mặt lớn ngoài ROI + mặt nhỏ trong ROI → `MOVE_TO_CENTER` (khẳng định luật "largest trước").
- Mặt trong ROI nhưng cạnh 100 px → `STEP_CLOSER`.
- Quy đổi `det`/`frame` cho khung 1920×1080 và 1280×720.
- ROI `null` → dùng toàn khung.

## 9. Đo lường
Tỉ lệ frame fail `STEP_CLOSER` / `MOVE_TO_CENTER` trong video thử. Chỉ số này giúp chỉnh ROI và vị trí đặt camera.

## 10. Tiêu chí hoàn thành
- [ ] Test pass; D-06 và D-07 được chốt sau khi thử lắp camera thực tế (đo khoảng cách đứng ứng với 110 px)
