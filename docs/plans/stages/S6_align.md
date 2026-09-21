# S6 — Căn chỉnh khuôn mặt về template ArcFace

**Milestone:** M1 (đã hiện thực lõi) + M3 (task M3-T16, bọc stage) · **Module:** `src/edgeface/pipeline/align.py`

## 1. Mục tiêu
Biến đổi similarity (xoay + tỉ lệ đều + tịnh tiến) để đưa 5 điểm mặt về template ArcFace, tạo ảnh 112×112 cho S7.

## 2. Input / Output
- **Input:** `Frame.image`, 5 điểm (nguồn theo D-09).
- **Output:** `StageResult(True, None, aligned)`. `aligned` là 112×112×3 uint8.

**Về màu:** spec ghi "112×112 RGB". Code giữ ảnh **BGR** ở S6, còn `ArcFace.preprocess` đổi sang RGB ngay trước khi tạo tensor. Kết quả tương đương spec; mục đích là mọi ảnh trong pipeline cùng một không gian màu. Quy ước này ghi rõ trong docstring và có test.

## 3. Thuật toán (đã có, M1)
Port từ `ims_id_server face_backend/src_recognition/face_align.py::estimate_norm/norm_crop` (mode `arcface`):
- Template `ARCFACE_SRC` (5 điểm, không gian 112×112).
- `M = umeyama_similarity(kps, ARCFACE_SRC)`: bản numpy thay cho `skimage.transform.SimilarityTransform`, vì skimage không có trên Nano.
- `cv2.warpAffine(img, M, (112, 112), borderValue=0)`.

Việc còn lại ở M3:
1. Hàm stage `run(frame, obs, cfg)` chọn nguồn điểm:
   - `align.kps_source = "scrfd"` → `Detection.kps`
   - `align.kps_source = "lmk106"` → rút 5 điểm từ 106 điểm: tâm mắt = trung bình các điểm viền mắt, chóp mũi, 2 khoé miệng (chỉ số lấy từ `landmark_index.py` của S5)
2. Kiểm tra sai số dư của phép Umeyama (trung bình khoảng cách sau biến đổi so với template). Nếu vượt `align.max_residual_px` → fail `LOOK_STRAIGHT` (điểm bất thường).

## 4. Config keys
`align.kps_source` (`scrfd|lmk106`, D-09), `align.image_size` 112, `align.max_residual_px` (đề xuất, chờ duyệt; `null` = không kiểm tra).

## 5. Giá trị cần xác nhận
- **D-09:** nguồn 5 điểm.
  - *SCRFD:* đề xuất, vì insightface huấn luyện và đánh giá ArcFace với kps của detector.
  - *106 điểm:* theo đúng chữ của spec ("5 điểm từ 106"). Có thể ổn định hơn trên frame nghiêng.

  Có thể quyết bằng ablation ở M9 (TAR@FAR của hai phương án).
- `align.max_residual_px`: giá trị hoặc bỏ kiểm tra.

## 6. File
- `src/edgeface/pipeline/align.py` (bổ sung `run`, `five_from_106`, residual)
- `tests/unit/test_align.py` (bổ sung)

## 7. Trường hợp biên
- 5 điểm thẳng hàng hoặc trùng nhau → `umeyama_similarity` báo `ValueError` → stage fail `LOOK_STRAIGHT`.
- Mặt sát biên → phần ngoài biên của crop là màu đen; chấp nhận (giống tham chiếu).

## 8. Test
- **Đã có (M1):** template tự khớp; kps xoay/tỉ lệ khớp về template; nội dung pixel đúng vị trí; parity với skimage (≤ 2 mức xám).
- **Bổ sung:** `five_from_106` trên bộ 106 điểm tổng hợp; residual lớn → fail; `kps_source` đọc từ config.

## 9. Đo lường
Latency S6 (< 1 ms kỳ vọng, cần xác nhận trên Nano), phân bố residual.

## 10. Tiêu chí hoàn thành
- [ ] Stage + test pass
- [ ] D-09 được chốt (hoặc giữ SCRFD và ghi ablation cho M9)
