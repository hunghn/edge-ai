# M3 — Kết quả pipeline S0–S8

**Ngày:** 2026-09-21 · **Thiết bị:** xem [`docs/device_inventory.md`](../device_inventory.md)

Tái lập:
```bash
python3 scripts/run_pipeline_offline.py --video <clip.mp4> --config configs/dev.yaml --out results/run
python3 tools/viz/overlay.py --video <clip.mp4> --out overlay.mp4     # xem bằng mắt gate nào chặn
python3 tools/viz/landmark_index.py                                    # kiểm chứng chỉ số 106 điểm
```

## 1. Latency từng stage trên Jetson Nano (TensorRT FP16)
Video thử: 60 frame 1280×720, một khuôn mặt, có 6 frame cố tình làm mờ.
Đã chạy `jetson_clocks`, engine build lúc máy rảnh (xem M2 §6.1 — cả hai điều kiện đều quan trọng).

| Stage | n | p50 (ms) | p95 (ms) | Ghi chú |
|---|---|---|---|---|
| S1 detect | 60 | **40.35** | 40.83 | letterbox 720p→640 + suy luận + NMS |
| S2 subject | 60 | 0.12 | 0.13 | thuần hình học |
| S3 coarse pose | 57 | 0.26 | 0.26 | 5 điểm, rẻ đúng như thiết kế |
| S4 anti-spoof | 57 | 16.15 | 20.30 | 2 crop + 2 suy luận |
| S5 landmark | 57 | 10.36 | 10.87 | 2d106det |
| S5 pose + IQA | 114 | 1.83 | 2.18 | solvePnP và Laplacian (2 lần gọi mỗi frame) |
| S6 align | 51 | 1.90 | 2.01 | |
| S7 embed | 51 | 15.33 | 15.38 | ArcFace |
| **e2e** | 60 | **89.04** | 93.44 | **≈ 11.2 FPS** |

Trước khi ghim xung nhịp, cùng phép đo cho e2e p50 96.30 ms và p95 **148.68** ms. Giá trị trung vị chỉ khá hơn 8%, nhưng **độ tản giảm hẳn**: p95 của S1 từ 71.4 xuống 40.8 ms. Với kiosk thì tính ổn định này quan trọng hơn vài mili giây trung bình.

Trên máy dev (x86, onnxruntime, CPU): e2e p50 **76.21 ms**, S1 32.23 ms, S4 8.55 ms, S7 23.53 ms.

**Nhận xét:** S1 chiếm 43% thời gian một frame. Nếu cần thêm tốc độ, hướng đầu tiên là giảm nhịp gọi detector kèm bám bbox, không phải tối ưu các stage nhỏ. Gate S3 hoạt động đúng mục đích: frame lệch mặt bị loại sau 42 ms thay vì 96 ms.

## 2. Hành vi các gate
| Kết quả | x86 | Nano | Diễn giải |
|---|---|---|---|
| Qua hết S1–S8 | 50/60 | 51/60 | |
| Dừng ở S5 (`HOLD_STILL`) | 6 | 6 | đúng 6 frame bị làm mờ |
| Dừng ở S2 (`STEP_CLOSER`) | 4 | 3 | các frame mặt nhỏ nhất |

Hai backend cho kết quả gate gần như trùng nhau; chênh lệch 1 frame nằm ở ca sát ngưỡng kích thước.

## 3. Ba phát hiện kỹ thuật

### 3.1 solvePnP trả về nghiệm "mặt nằm sau camera"
`cv2.solvePnP(..., SOLVEPNP_ITERATIVE)` khởi tạo từ homography phẳng, và với khuôn mặt nhỏ trong khung, nó hội tụ vào **nghiệm phản chiếu**: trên ảnh fixture, `tz = −3612 mm` (mặt nằm sau camera) và roll ≈ 180° cho một chân dung dựng thẳng. Toàn bộ frame khi đó bị chặn ở S5.

Cách xử lý trong `pipeline/pose.py::solve_head_pose`: khởi tạo bằng `SOLVEPNP_EPNP`, tinh chỉnh bằng `SOLVEPNP_ITERATIVE`, và **từ chối mọi nghiệm có `tz ≤ 0`**. `SOLVEPNP_SQPNP` sẽ gọn hơn nhưng cần OpenCV ≥ 4.5, trong khi JetPack 4.6 chỉ có 4.1.1. Test `test_solve_head_pose_beats_plain_iterative_on_real_landmarks` khoá lại đúng ca này.

### 3.2 Mô hình 3D trung bình gây lệch pitch có hệ thống
Sau khi sửa, ảnh chân dung mẫu (nhìn bằng mắt là chính diện) vẫn cho **pitch ≈ −17°**, vượt ngưỡng ±15° của spec. Landmark và bbox đều đúng, xem `docs/figures/lmk106_index.png` và ảnh overlay.

Nguyên nhân là mô hình 3D dùng chung cho mọi người cộng với nội tham số camera xấp xỉ (`f = chiều rộng ảnh`, **D-10**). Cùng một khuôn mặt đặt trong khung 512×512 cho pitch −12.5°, còn trong khung 1280×720 cho −15.9°: giá trị phụ thuộc vào giả định tiêu cự.

**Hệ quả cần xử lý ở M9:** hoặc hiệu chuẩn camera thật (D-10), hoặc đo độ lệch nền trên vài chục ảnh chính diện rồi chốt lại ngưỡng pose. **Không nên** giữ nguyên ±15° khi chưa biết độ lệch nền của chính camera kiosk, vì sẽ loại oan rất nhiều frame.

### 3.3 Chỉ số 106 landmark được kiểm chứng, không lấy theo giả định
`tools/viz/landmark_index.py` suy ra bảng chỉ số từ dữ liệu (điểm gần nhất với từng keypoint SCRFD, cực trị từng nhóm) trên cả hai ảnh fixture, rồi đối chiếu với hằng số đã ghi trong `pipeline/landmark_index.py`. Kết quả: cằm 0, chóp mũi 86, khoé mắt ngoài 35/93, khoé miệng 52/61 — trùng với cách dùng trong repo tham chiếu, nhưng giờ có bằng chứng.

## 4. Trạng thái các giá trị còn mở
| Mã | Ảnh hưởng thấy được trong M3 |
|---|---|
| D-06 (ROI) | `null` → dùng toàn khung, có cảnh báo một lần |
| D-07 (không gian đo 110 px) | mặc định `det`: ở khung 1280 tương đương 220 px, ở 1920 là 330 px |
| D-08 (`quality_score`) | `null` → giữ frame theo thứ tự đến trước; 3 công thức A/B/C đã cài sẵn để so ở M9 |
| D-10 (nội tham số) | xem §3.2 — nay là mục **cần ưu tiên** |
| D-11 (vùng đo blur) | đang dùng crop 0.8× resize 112×112 |
| D-15 (`k_yaw`) | `null` → S3 chỉ gate roll |
| D-31 (liên tục chủ thể) | `null` → không reset; đã có test cho cả ba cơ chế |

## 5. Tiêu chí hoàn thành M3
- [x] 9 stage có test unit (150 test pass trên cả x86 và Nano)
- [x] `run_pipeline_offline.py` xuất `frames.csv`, `embeddings.npz`, `summary.md`
- [x] Chạy trên Nano với TensorRT, có bảng latency
- [x] Không hardcode ngưỡng: mọi giá trị đọc từ config
- [x] Đo lại với `jetson_clocks` và engine build lúc máy rảnh
- [ ] Đo lại với camera lắp đúng vị trí kiosk (sau khi chốt D-06/D-07)
