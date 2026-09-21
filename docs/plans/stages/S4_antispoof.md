# S4 — Chống giả mạo (MiniFASNetV2 + MiniFASNetV1SE)

**Milestone:** M3 (task M3-T14); lưu bằng chứng và quyết định cấp phiên ở M5 · **Module:** `src/edgeface/pipeline/antispoof.py` · **Wrapper:** `src/edgeface/models/minifasnet.py` (đã có từ M1)

## 1. Mục tiêu
Phân loại khuôn mặt là thật hay giả (ảnh in / phát lại trên màn hình) chỉ bằng ảnh RGB đơn. Gate theo frame: **argmax = real và p_real ≥ 0.85**. Nếu fail thì trả `spoof_suspect` và lưu ảnh bằng chứng.

## 2. Input / Output
- **Input:** `Frame.image` (khung đầy đủ BGR), `Detection` do S2 chọn.
- **Output:** `StageResult(ok, reason, SpoofScore)`
  - `SpoofScore = (p_real, probs(3,), argmax, probs_v2, probs_v1se)`
  - `reason = "SPOOF_SUSPECT"` khi fail

## 3. Thuật toán
Port từ `ims_id_server tools/tools.py::check_real_face(mode="both")` và `generate_patches.py::CropImage`:
1. `bbox_xywh = [x1, y1, x2 − x1, y2 − y1]` (**không** phải xyxy). Toạ độ trên khung đầy đủ.
2. Model V2: `crop_image(img, bbox_xywh, scale=2.7, 80, 80)`. Model V1SE: `scale=4.0`.
3. Tensor: float32 CHW **BGR 0–255, không chia 255**.
4. `probs_i = softmax(logits_i)`; `fused = (probs_v2 + probs_v1se) / 2` (D-05).
5. `argmax = fused.argmax()`; `p_real = fused[1]` (index 1 = real; 0 = print, 2 = replay).
6. `ok = (argmax == 1) and (p_real ≥ antispoof.p_real_min)`.

Khác với repo tham chiếu: tham chiếu dùng ngưỡng 0.65 và đảo nhãn khi thấp hơn ngưỡng; ở đây dùng gate thẳng theo spec.

**Quyết định cấp phiên (M5, không thuộc stage):** stage chỉ quyết định từng frame. Session (M5) đếm số frame spoof trong cửa sổ thu thập để ra `SPOOF_SUSPECT` cho cả phiên. Luật gộp là D-30.

**Ảnh bằng chứng (M5):** khi phiên kết luận `SPOOF_SUSPECT`, lưu ảnh của frame có `p_real` thấp nhất theo D-14 qua `storage/evidence.py`. Stage chỉ trả dữ liệu, **không ghi đĩa**, để stage giữ được tính thuần (dễ test).

## 4. Config keys
`antispoof.p_real_min` 0.85, `antispoof.real_class_index` 1, `antispoof.crops[] {model, scale}`, `antispoof.input_size` [80, 80], `antispoof.fusion` (`mean`, chờ D-05).

## 5. Giá trị cần xác nhận
- **D-05:** 0.85 áp lên trung bình hai softmax (đề xuất) hay lên tổng (thang 0–2).
- **D-14:** ảnh bằng chứng lưu gì và giữ bao lâu.
- **D-16:** giữ 2 engine riêng hay gộp.
- **D-30 (mới):** luật gộp spoof cấp phiên, ví dụ "≥ 1 frame spoof" hay "≥ M trong K frame".

## 6. File
- `src/edgeface/pipeline/antispoof.py`
- `tests/unit/test_antispoof_stage.py` (backend giả trả logits định sẵn)
- (M5) `src/edgeface/storage/evidence.py`

## 7. Trường hợp biên
- bbox chạm biên ảnh: `CropImage` tự dịch vào trong, đã có test parity pixel-exact từ M1.
- bbox cực nhỏ (w hoặc h < 1): trả fail `SPOOF_SUSPECT`? **Không**: trả `StageResult(False, "INVALID_BBOX")` để không tạo cảnh báo giả mạo sai. S2 thường đã chặn trường hợp này.
- Hai model mâu thuẫn (V2 nói real, V1SE nói replay): quyết định theo tổng đã gộp; log cả hai xác suất để phân tích ở M9.

## 8. Test
- **Unit:** fused đúng công thức; argmax ≠ 1 mà p_real cao (không thể xảy ra với softmax 3 lớp khi p_real > 0.5, nhưng vẫn test với số biên 0.34/0.33/0.33); p_real = 0.849 → fail, 0.85 → ok; bbox được chuyển sang xywh đúng.
- **Parity (M1, đã có):** xác suất từng model khớp torch < 1e-4.
- **Chức năng (M8/M9):** bộ ảnh tấn công thật (in A4, điện thoại, tablet) → APCER/BPCER.

## 9. Đo lường
Latency S4 (2 lần suy luận + 2 crop), phân bố p_real trên người thật và tấn công, APCER / BPCER / ACER (M9).

## 10. Tiêu chí hoàn thành
- [ ] Stage + test pass
- [ ] D-05 được chốt
- [ ] Latency trên Nano được ghi lại
