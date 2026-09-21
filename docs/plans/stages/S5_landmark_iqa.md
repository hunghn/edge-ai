# S5 — Landmark 106 điểm + tư thế tinh + đánh giá chất lượng ảnh (IQA)

**Milestone:** M3 (task M3-T15) · **Module:** `src/edgeface/pipeline/pose.py` (`fine_pose`), `src/edgeface/pipeline/quality.py` · **Wrapper:** `src/edgeface/models/landmark106.py` (đã có từ M1)

## 1. Mục tiêu
Loại frame chưa đủ tốt để trích embedding. Gate:
- |yaw| ≤ 15°, |pitch| ≤ 15°, |roll| ≤ 10°
- blur (Laplacian variance) ≥ 60
- 60 ≤ độ sáng ≤ 200

Nếu fail thì **bỏ frame và chờ frame tốt hơn**. Đây không phải lỗi cấp phiên.

## 2. Input / Output
- **Input:** `Frame.image`, `Detection` (bbox).
- **Output:** `StageResult(ok, reason, {lmk106 (106×2), yaw, pitch, roll, blur, lum})`.
- `reason ∈ {LOOK_STRAIGHT, HOLD_STILL, TOO_DARK, TOO_BRIGHT}`. Ưu tiên khi nhiều điều kiện fail cùng lúc: pose → sáng/tối → blur (người dùng sửa được theo thứ tự này).

## 3. Thuật toán

### 3.1 Landmark (đã có từ M1)
Crop quanh tâm bbox, cạnh = max(w, h) × 1.5 → 192×192; tensor RGB mean 0 / std 1 (C-06); output [−1, 1] → (x+1)×96 → biến đổi affine ngược về khung đầy đủ.

### 3.2 Chỉ số landmark: kiểm chứng trước khi dùng (task M3-T15a)
Repo tham chiếu (`tools.py::face_analysis`) dùng: mắt trái 35–42, mắt phải 89–96, miệng 52–71, chóp mũi 86, sống mũi trên 72, cằm 0, má 12/28. Đây là **giả định cần kiểm chứng**, không dùng ngay.
- Viết `tools/viz/landmark_index.py`: vẽ số thứ tự 106 điểm lên ảnh fixture, lưu PNG.
- Chốt bảng chỉ số trong `src/edgeface/pipeline/landmark_index.py` (hằng số, có comment nguồn và ảnh kiểm chứng trong `docs/figures/`).

### 3.3 Tư thế tinh bằng solvePnP
- **Điểm 3D:** mô hình khuôn mặt trung bình 6 điểm (chóp mũi, cằm, khoé ngoài mắt trái/phải, khoé miệng trái/phải) theo mô hình khuôn mặt chuẩn dùng phổ biến trong ví dụ head-pose của OpenCV. Toạ độ ghi trong code kèm nguồn.
- **Điểm 2D:** 6 chỉ số tương ứng trong 106 điểm (từ §3.2).
- **Nội tham số (D-10):** mặc định `f = W`, `cx = W/2`, `cy = H/2`, không méo. Nếu D-10 chốt hiệu chuẩn thì đọc `camera.K`, `camera.dist` từ config.
- `cv2.solvePnP(model3d, pts2d, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)` → `cv2.Rodrigues` → ma trận R → góc Euler bằng `cv2.RQDecomp3x3`.
- Quy ước dấu yaw/pitch/roll thống nhất với S3 và được khoá bằng test.

### 3.4 IQA (`quality.py`)
- **Vùng tính (D-11):** đề xuất crop bbox thu nhỏ 80% quanh tâm (bỏ nền), resize về 112×112, chuyển sang ảnh xám. Cố định kích thước vì phương sai Laplacian phụ thuộc độ phân giải: cùng một khuôn mặt nhưng crop to hơn thì blur khác.
- `blur = cv2.Laplacian(gray, cv2.CV_64F).var()` (như `tools.py::detect_blur`)
- `lum = gray.mean()` (tham chiếu làm mờ 5×5 trước khi lấy mean; mean không đổi đáng kể nên bỏ bước này)
- Không tự tăng sáng (tham chiếu có gamma cho ảnh tối; spec không yêu cầu). Nếu cần, bổ sung sau khi được duyệt.

## 4. Config keys
`landmark.input_size` 192, `landmark.bbox_expand` 1.5, `pose_fine.{yaw,pitch,roll}_max_deg` 15/15/10, `iqa.blur_min` 60, `iqa.lum_min` 60, `iqa.lum_max` 200, `iqa.crop_shrink` (D-11), `iqa.crop_size` (D-11), `camera.K`, `camera.dist` (D-10).

## 5. Giá trị cần xác nhận
- **D-10:** camera intrinsics xấp xỉ hay hiệu chuẩn.
- **D-11:** định nghĩa vùng tính blur/lum. Ngưỡng 60 chỉ có nghĩa sau khi chốt mục này.
- **Chỉ số 106 điểm:** kiểm chứng ở M3-T15a, không cần người dùng chốt nhưng phải có ảnh minh chứng.

## 6. File
- `src/edgeface/pipeline/pose.py` (`fine_pose`), `src/edgeface/pipeline/landmark_index.py`, `src/edgeface/pipeline/quality.py`
- `tools/viz/landmark_index.py`, `docs/figures/lmk106_index.png`
- `tests/unit/test_pose_fine.py`, `tests/unit/test_quality.py`

## 7. Trường hợp biên
- solvePnP không hội tụ hoặc trả NaN → fail `LOOK_STRAIGHT`.
- Góc Euler gần ±180° do nhập nhằng hướng trục → chuẩn hoá về [−90, 90] (có test).
- Mặt quá tối → Laplacian thấp → báo `TOO_DARK` trước `HOLD_STILL` (thứ tự ưu tiên §2).
- Crop chạm biên ảnh → phần ngoài biên là pixel 0, làm lệch `lum`: chỉ tính trên phần giao với khung.

## 8. Test
- **Pose:** chiếu phối cảnh mô hình 3D với yaw/pitch/roll đã biết (±30°) → `fine_pose` khôi phục với sai số ≤ 2°.
- **Blur:** ảnh bàn cờ nét > ảnh đã `GaussianBlur` (đơn điệu theo sigma).
- **Lum:** ảnh xám đồng màu 50 / 128 / 220 → TOO_DARK / ok / TOO_BRIGHT.
- **Parity landmark (M1, đã có).**

## 9. Đo lường
Latency S5 (landmark infer + solvePnP + IQA), phân bố yaw/pitch/roll/blur/lum trên video thử, tỉ lệ frame bị loại theo từng lý do.

## 10. Tiêu chí hoàn thành
- [ ] Ảnh minh chứng chỉ số 106 điểm
- [ ] Test pass
- [ ] D-10 và D-11 được chốt
- [ ] Phân bố các chỉ số trên video thử được ghi lại để hỗ trợ hiệu chuẩn
