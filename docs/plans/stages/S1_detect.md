# S1 — Phát hiện khuôn mặt (SCRFD det_500m)

**Milestone:** M3 (task M3-T11) · **Module:** `src/edgeface/pipeline/detect.py` · **Wrapper:** `src/edgeface/models/scrfd.py` (đã có từ M1)

## 1. Mục tiêu
Tìm mọi khuôn mặt trong khung hình, kèm bbox, 5 keypoint và score. Gate: **score ≥ 0.6**. Nếu 0 mặt thì trả về IDLE.

## 2. Input / Output
- **Input:** `Frame` (khung đầy đủ BGR).
- **Output (ok):** `StageResult(True, None, [Detection, ...])`, sắp xếp theo score giảm dần; toạ độ theo khung đầy đủ.
- **Output (fail):** `StageResult(False, "NO_FACE", [])`.

## 3. Thuật toán (đã hiện thực trong wrapper, M1)
1. Letterbox về 640×640 (giữ tỉ lệ, pad góc dưới phải), rồi tensor RGB (x−127.5)/128 (C-07).
2. Suy luận, thu 9 output. Output được nhận diện theo shape: (N,1) score, (N,4) bbox, (N,10) kps; N = (640/s)²×2 cho s ∈ {8, 16, 32}.
3. Decode: `distance2bbox` và `distance2kps` quanh tâm anchor × stride.
4. Lọc score ≥ `detect.score_min`, chia cho hệ số letterbox, NMS với IoU 0.4 (theo `scrfd.py::SCRFD.nms`, quy ước +1 pixel).

Phần việc mới ở M3 chỉ là hàm stage mỏng:
```python
@timed("S1")
def run(frame, detector, cfg):
    dets = detector.detect(frame.image, score_min=cfg["detect"]["score_min"])
    return ok(dets) if dets else fail(GuidanceCode.NO_FACE, [])
```
Có thể thêm `detect.max_faces` để cắt danh sách trước S2 (tiết kiệm CPU), mặc định không cắt.

## 4. Config keys
`detect.input_size` [640, 640], `detect.score_min` 0.6, `detect.nms_iou` 0.4, `detect.max_faces` (tuỳ chọn).

## 5. Giá trị cần xác nhận
Không có. Các giá trị trên đều từ spec hoặc repo tham chiếu.

## 6. File
- `src/edgeface/pipeline/detect.py`
- `tests/unit/test_detect_stage.py` (dùng `_FakeBackend` giống `test_scrfd_decode.py`)

## 7. Trường hợp biên
- Ảnh đen, không mặt → `NO_FACE`.
- Mặt sát mép ảnh: bbox có thể âm hoặc vượt khung. S1 **không** clip (giữ đúng hành vi tham chiếu); S2/S4 tự xử lý.
- Khung dọc (tỉ lệ ≠ 16:9): letterbox vẫn đúng (đã có test `wide` / `square` ở parity).
- Engine FP16 cho score lệch nhẹ quanh ngưỡng 0.6: chấp nhận, ghi nhận trong M2 parity.

## 8. Test
- **Unit:** stage trả `NO_FACE` khi backend giả không có mặt; trả đúng thứ tự score; truyền đúng `score_min` từ config.
- **Parity (đã có, M1):** `tests/parity/test_models_parity.py::test_scrfd`.
- **Device (M2):** engine FP16 vs ONNX.

## 9. Đo lường
Latency S1 tách pre/infer/post (p50/p95), số mặt/frame, tỉ lệ frame `NO_FACE`.

## 10. Tiêu chí hoàn thành
- [ ] Stage + test unit pass
- [ ] Latency S1 trên Nano có trong báo cáo M3
