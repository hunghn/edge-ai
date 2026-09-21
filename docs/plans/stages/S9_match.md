# S9 — So khớp với gallery

**Milestone:** M5 (task M5-T10) · **Module:** `src/edgeface/pipeline/matcher.py`, `src/edgeface/gallery/gallery.py`

## 1. Mục tiêu
So ≤ 5 embedding của phiên với gallery bệnh nhân trong ngày bằng cosine (numpy brute-force). Tìm top1/top2 và bỏ phiếu **3-of-5**. Nếu dưới ngưỡng thì chuyển sang xác nhận thủ công.

## 2. Input / Output
- **Input:** `E` (K×512, K ≤ 5, L2 = 1), `Gallery` (xem §3.1), config `match.*`.
- **Output:** `MatchResult`:
  ```
  top1_code, top1_score, top2_code, top2_score, margin,
  votes (số frame top1 == top1_code), k,
  per_frame: [(top1_code, top1_score, top2_code, top2_score)],
  passed_threshold: True | False | None   # None khi ngưỡng chưa chốt
  ```

## 3. Thuật toán

### 3.1 Gallery (`gallery/gallery.py`)
- Nạp từ SQLite (M4) mọi `face_templates` thoả:
  - bệnh nhân chưa hết hạn
  - chưa bị thu hồi
  - `recognizer_sha256` bằng model đang chạy
- Cấu trúc trong RAM: `T` (M×512 float32), `owner` (M, int → chỉ số bệnh nhân), `codes` (N mã BN).
- **Reload:** engine gọi `gallery.refresh_if_changed()` **chỉ giữa hai phiên**, so `gallery_meta.version`. Không reload giữa phiên.
- **Quy mô:** 60 BN × 5 template = 300 dòng, khoảng 0.6 MB, nhân ma trận < 1 ms.

### 3.2 So khớp
1. `S = E @ T.T` (K×M).
2. Gộp theo bệnh nhân (D-03, đề xuất `max`): `P[k, n] = max_{m: owner[m] = n} S[k, m]` (K×N), dùng `np.maximum.reduceat` trên `T` đã sắp theo owner.
3. Với mỗi frame k: `top1_k`, `top2_k` = 2 bệnh nhân có P cao nhất. Nếu N = 1 thì `top2 = None, score = −1`.
4. **Vote:** `top1_code` = bệnh nhân xuất hiện nhiều nhất trong các `top1_k` (hoà thì lấy trung bình điểm cao hơn); `votes` = số lần xuất hiện.
5. `top1_score` = trung bình `P[k, top1_code]` trên các frame bầu cho nó; `top2_score` = trung bình top2 tương ứng; `margin = top1_score − top2_score`.
6. `passed_threshold`:
   - `None` nếu `match.threshold` hoặc `match.margin_top1_top2` là `null`.
   - Ngược lại: `votes ≥ vote_k and top1_score ≥ threshold and margin ≥ margin_min`.

Luật vote được hiểu là "≥ `vote_k` frame bầu cho cùng một BN", với số frame K ≤ `vote_n`. Khi K < `vote_k` (ví dụ chỉ có 3 frame) vẫn áp dụng ngưỡng tuyệt đối `vote_k = 3`.

## 4. Config keys
`match.threshold` (D-01), `match.margin_top1_top2` (D-02), `match.vote_k` 3, `match.vote_n` 5, `match.template_agg` (`max|mean`, D-03).

## 5. Giá trị cần xác nhận
- **D-01, D-02:** ngưỡng, hiệu chuẩn ở M9 trên tập dev (không dùng tập test).
- **D-03:** gộp template bằng `max` hay `mean`.
- **D-17:** cách hiểu luật 3-of-5 (§3.2 bước 6).

## 6. File
- `src/edgeface/gallery/{__init__,gallery}.py`, `src/edgeface/pipeline/matcher.py`
- `tests/unit/test_matcher.py`, `tests/unit/test_gallery.py`

## 7. Trường hợp biên
- Gallery rỗng → `MatchResult` với `top1_code = None`; S10 xử lý.
- Tất cả template của một BN bị lọc (sai model sha) → BN không xuất hiện trong gallery; ghi log cảnh báo một lần cho mỗi phiên bản gallery.
- K = 0 → không gọi S9 (S8 đã trả `LOW_QUALITY`).
- Hai BN trùng gần như tuyệt đối (cùng người enroll hai mã) → margin ≈ 0 → không pass; M5 cảnh báo lúc enroll (D-20).

## 8. Test
- Gallery tổng hợp: vector ngẫu nhiên trực giao + nhiễu; probe gần BN #3 → top1 = #3, votes = 5.
- 2 frame bầu A, 3 frame bầu B → top1 = B, votes = 3.
- Gộp `max` so với `mean` cho kết quả khác nhau trên ca có 1 template lệch.
- Ngưỡng `null` → `passed_threshold is None`.
- Lọc `recognizer_sha256` và revoked.
- **Hiệu năng:** N = 300 template, 1000 lần < 1 ms trung bình trên x86 (đo lại trên Nano).

## 9. Đo lường
Latency S9; phân bố `top1_score` genuine/impostor, margin, votes (dữ liệu cho M9).

## 10. Tiêu chí hoàn thành
- [ ] Test pass
- [ ] Engine chạy được với ngưỡng `null`
- [ ] D-17 và D-03 được chốt
