# S8 — Gom best-frame

**Milestone:** M3 (task M3-T18) · **Module:** `src/edgeface/pipeline/best_frame.py`

## 1. Mục tiêu
Gom tối đa **5 embedding tốt nhất** của **cùng một người** trong cửa sổ **≤ 1.5 s**. Nếu có < 3 frame đạt thì kết luận `low_quality`.

## 2. Input / Output
- **Input mỗi frame:** `Embedding`, các chỉ số chất lượng (det score, yaw/pitch/roll, blur, lum, raw_norm), `Detection.bbox`, `ts`.
- **Output:** trạng thái của collector:
  - `COLLECTING`: chưa đủ.
  - `READY(embeddings[≤K], qualities)`: đủ điều kiện, chuyển sang S9.
  - `LOW_QUALITY(n_good)`: hết cửa sổ mà n_good < `min_good`.

## 3. Thuật toán
```
class BestFrameCollector:
    start(ts)                      # mở cửa sổ khi có frame hợp lệ đầu tiên
    add(emb, quality, bbox, ts)    # giữ heap top-K theo quality
    observe_miss(ts, reason)       # frame bị gate loại: không cộng, chỉ cập nhật thời gian
    poll(ts) -> COLLECTING | READY | LOW_QUALITY
    reset(reason)
```
1. **Mở cửa sổ:** tại frame đầu tiên qua được S7; `t0 = ts`.
2. **Thêm:** giữ tối đa `k_max` embedding có `quality` cao nhất (min-heap).
3. **Kết thúc:**
   - Đạt `k_max` frame hợp lệ → `READY` ngay (không cần chờ hết 1.5 s).
   - `ts − t0 ≥ window_s` → `READY` nếu `n ≥ min_good`, ngược lại `LOW_QUALITY`.
4. **Tính liên tục của chủ thể** (tránh trộn embedding của hai người):
   - Nếu IoU giữa bbox mới và bbox cuối < `continuity.iou_min` → `reset("SUBJECT_CHANGED")`.
   - Nếu không có mặt hợp lệ quá `continuity.max_gap_s` giây → `reset("SUBJECT_LOST")`.
   - *Tuỳ chọn:* cosine của embedding mới với trung bình các embedding đã có < `continuity.cos_min` → reset.
5. `n_good` là số frame qua đủ gate S1–S7 trong cửa sổ, **kể cả** frame bị đẩy khỏi heap.

**`quality_score` (D-08):** spec chưa định nghĩa. Các phương án đề xuất để chọn (hoặc chọn qua ablation ở M9):

| PA | Công thức | Ưu / nhược |
|---|---|---|
| A | `det_score × (1 − |yaw|/yaw_max) × (1 − |pitch|/pitch_max) × min(1, blur/blur_ref)` | Dễ giải thích; cần thêm `blur_ref` |
| B | Tổng có trọng số các chỉ số đã chuẩn hoá về [0,1] | Linh hoạt; nhiều tham số |
| C | `raw_norm` của ArcFace (độ lớn feature tương quan với chất lượng) | Không tham số; phụ thuộc model |

Code hiện thực cả 3 dưới dạng hàm có tên; config chọn `best_frame.quality_score: A|B|C`. Khi `null`, dùng thứ tự đến trước (FIFO) và ghi cảnh báo một lần.

## 4. Config keys
`best_frame.k_max` 5, `best_frame.window_s` 1.5, `best_frame.min_good` 3, `best_frame.quality_score` (D-08), `best_frame.quality_params`, `best_frame.continuity.{iou_min, max_gap_s, cos_min}` (D-31).

## 5. Giá trị cần xác nhận
- **D-08:** công thức `quality_score`.
- **D-31 (mới):** ngưỡng liên tục chủ thể (`iou_min`, `max_gap_s`, có dùng `cos_min` hay không).

## 6. File
- `src/edgeface/pipeline/best_frame.py`
- `tests/unit/test_best_frame.py` (đồng hồ giả, không `sleep`)

## 7. Trường hợp biên
- Người rời đi giữa cửa sổ → `SUBJECT_LOST`, không kết luận `LOW_QUALITY` (tránh làm tăng sai tỉ lệ vận hành).
- Frame đến không đều (FPS thấp): chỉ dùng `ts`, không đếm frame.
- `k_max < min_good` → `config.validate` đã chặn.

## 8. Test
- 5 frame tốt trong 0.6 s → `READY` ngay với 5 embedding.
- 2 frame tốt trong 1.5 s → `LOW_QUALITY(n_good=2)`.
- 8 frame tốt → giữ đúng 5 frame có quality cao nhất.
- bbox nhảy (IoU = 0) → reset.
- `quality_score = null` → FIFO.

## 9. Đo lường
Thời gian từ frame hợp lệ đầu tiên đến `READY` (p50/p95); phân bố n_good; tỉ lệ `LOW_QUALITY` và `SUBJECT_CHANGED`/`SUBJECT_LOST` (chỉ số vận hành trong spec §5).

## 10. Tiêu chí hoàn thành
- [ ] Test pass
- [ ] D-08 và D-31 được chốt, hoặc đưa vào ablation M9 với mặc định có ghi chú
