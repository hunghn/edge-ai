# S7 — Trích xuất vector đặc trưng (ArcFace w600k_mbf)

**Milestone:** M1 (wrapper) + M3 (task M3-T17, stage) · **Module:** `src/edgeface/pipeline/embed.py` · **Wrapper:** `src/edgeface/models/arcface.py`

## 1. Mục tiêu
Sinh vector 512 chiều, chuẩn hoá L2, từ ảnh mặt đã căn chỉnh.

## 2. Input / Output
- **Input:** `aligned` 112×112 BGR (S6).
- **Output:** `StageResult(True, None, Embedding(frame_id, ts, vector(512,) float32 L2 = 1, quality=None))`. `quality` được S8 điền.
- Kèm theo `raw_norm` (chuẩn L2 trước khi chuẩn hoá) trong `data` để thử làm tín hiệu chất lượng ở S8/M9.

## 3. Thuật toán (đã có, M1)
BGR → RGB, (x − 127.5)/127.5, NCHW, batch 1 → suy luận → `l2_normalize`. Port từ `arcface_onnx.py::get_feat`.

Việc ở M3:
- Hàm stage `run(aligned, recognizer)`, bọc `@timed("S7")`.
- Kiểm tra `np.isfinite(vector).all()` và `raw_norm > eps`; nếu không đạt → `StageResult(False, "EMBED_INVALID")` và log lỗi. FP16 tràn số có thể sinh NaN, đây là tín hiệu quan trọng khi chạy trên Nano.
- **Phiên bản model:** mọi embedding lưu xuống DB (M4/M5) đều kèm `recognizer_sha256` lấy từ manifest. Embedding của model khác không được so với nhau (S9 lọc).

## 4. Config keys
`models.recognizer` (`w600k_mbf`); không có ngưỡng.

## 5. Giá trị cần xác nhận
Không có.

## 6. File
- `src/edgeface/pipeline/embed.py`
- `tests/unit/test_embed_stage.py`

## 7. Trường hợp biên
- Output NaN/Inf → fail như trên.
- Output shape khác (1, 512) → `ValueError` khi nạp model (kiểm tra 1 lần ở `engine/models.py`).

## 8. Test
- **Unit:** backend giả trả vector cố định → output có chuẩn 1; backend giả trả NaN → `EMBED_INVALID`.
- **Parity (M1, đã có):** cosine > 0.999 với tham chiếu.
- **Device (M2):** cosine FP16 vs FP32 ≥ 0.99.

## 9. Đo lường
Latency S7, phân bố `raw_norm`.

## 10. Tiêu chí hoàn thành
- [ ] Stage + test pass
- [ ] Latency trên Nano được ghi lại
