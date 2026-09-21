# S3 — Lọc tư thế thô từ 5 keypoint

**Milestone:** M3 (task M3-T13) · **Module:** `src/edgeface/pipeline/pose.py` (hàm `coarse_pose`)

## 1. Mục tiêu
Ước lượng nhanh yaw và roll từ 5 keypoint của SCRFD, **không tốn thêm suy luận**. Gate: |yaw| ≤ 25°, |roll| ≤ 20°. Nếu fail thì hướng dẫn "nhìn thẳng" và **không gọi S4**, để tiết kiệm 2 lần suy luận MiniFASNet.

## 2. Input / Output
- **Input:** `Detection.kps` (5×2, thứ tự theo SCRFD: mắt trái trên ảnh, mắt phải trên ảnh, mũi, khoé miệng trái, khoé miệng phải).
- **Output (ok):** `StageResult(True, None, {"yaw": deg, "roll": deg})`.
- **Output (fail):** `StageResult(False, "LOOK_STRAIGHT", {"yaw", "roll"})`.

## 3. Thuật toán
Repo tham chiếu dùng tỉ lệ khoảng cách trên 106 điểm (`tools.py::face_analysis`, `face_RL_rate`) và không quy ra độ. Spec yêu cầu ngưỡng theo độ, nên S3 dùng công thức hình học riêng:

1. **Roll:** `roll = degrees(atan2(ey_r − ey_l, ex_r − ex_l))` (góc của đường nối hai mắt).
2. **Khử roll:** xoay 5 điểm quanh trung điểm hai mắt một góc −roll.
3. **Yaw (sau khi khử roll):**
   - `eye_mid = (e_l + e_r)/2`, `half_iod = |e_r − e_l|/2`
   - `mouth_mid = (m_l + m_r)/2`
   - `r = (nose_x − (eye_mid_x + mouth_mid_x)/2) / half_iod` (độ lệch ngang của mũi so với trục giữa mặt, chuẩn hoá theo nửa khoảng cách hai mắt)
   - `yaw = degrees(asin(clip(r / k_yaw, −1, 1)))`
4. `k_yaw` là hệ số hình học: độ lệch chuẩn hoá tối đa khi mặt quay 90°. **Không tự đặt**; được hiệu chuẩn (D-15) bằng cách hồi quy trên cùng video, lấy yaw từ solvePnP của S5 làm nhãn. Trong lúc chưa hiệu chuẩn, `pose_coarse.k_yaw` để `null`; khi đó stage **chỉ gate theo roll**, bỏ qua yaw và ghi cảnh báo một lần.
5. **Dấu:** yaw > 0 khi mũi lệch sang phải *trên ảnh*. Quy ước này ghi trong docstring và thống nhất với S5.

## 4. Config keys
`pose_coarse.yaw_max_deg` 25, `pose_coarse.roll_max_deg` 20, `pose_coarse.k_yaw` (null đến khi hiệu chuẩn).

## 5. Giá trị cần xác nhận
- **D-15:** cách quy đổi sang độ và giá trị `k_yaw` sau hiệu chuẩn. Phương án thay thế nếu sai số lớn: dùng trực tiếp ngưỡng tỉ lệ `r` thay cho độ, nhưng như vậy khác spec nên phải được đồng ý.

## 6. File
- `src/edgeface/pipeline/pose.py` (`coarse_pose`, `_deroll`)
- `tests/unit/test_pose_coarse.py`
- `tools/calib/fit_k_yaw.py` (dev): đọc `frames.csv` từ `run_pipeline_offline` (có cả `r` và yaw của S5), fit `k_yaw` bằng least squares, in sai số MAE

## 7. Trường hợp biên
- Hai mắt trùng điểm (`half_iod ≈ 0`): trả fail `LOOK_STRAIGHT`, không chia cho 0.
- Nghiêng đầu 180° (ảnh lộn ngược): roll ≈ ±180 → fail.
- Keypoint nằm ngoài khung hình: vẫn tính được (toạ độ âm hợp lệ).

## 8. Test
- **Dữ liệu tổng hợp:** lấy mô hình 3D 5 điểm (mắt, mũi, miệng) → xoay yaw/roll đã biết → chiếu phối cảnh → so roll với sai số ≤ 1°. Kiểm tra dấu và tính đơn điệu của `r` theo yaw.
- Kiểm tra `k_yaw = null` thì chỉ gate roll.
- Roll 30° → fail; roll 10°, yaw 0 → ok.

## 9. Đo lường
Latency (kỳ vọng < 0.1 ms, chỉ để xác nhận), MAE yaw so với solvePnP trên video thử (báo cáo trong kết quả hiệu chuẩn), tỉ lệ frame bị chặn ở S3.

## 10. Tiêu chí hoàn thành
- [ ] Test pass
- [ ] `k_yaw` được hiệu chuẩn, MAE được ghi lại, và D-15 được chốt
