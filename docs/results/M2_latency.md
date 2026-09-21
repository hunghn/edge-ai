# M2 — Kết quả đo latency từng model trên Jetson Nano

**Ngày đo:** 2026-09-21 · **Thiết bị:** xem [`docs/device_inventory.md`](../device_inventory.md)
**Chế độ nguồn:** nvpmodel mode 0 (MAXN 10 W), đã chạy `jetson_clocks` · **Precision:** FP16 · **Batch:** 1 · **Engine build lúc máy rảnh** (quan trọng, xem §6.1)

Tái lập:
```bash
ssh nano 'cd ~/edge-ai && python3 scripts/bench_model.py --all --warmup 30 --iters 200 --tegrastats --csv bench.csv'
```

## 1. Latency từng model (p50, ms)

| Model | Tiền xử lý | Suy luận | Suy luận p95 | Hậu xử lý | Tổng | ~FPS nếu chạy riêng |
|---|---|---|---|---|---|---|
| det_500m (SCRFD 640×640) | 10.54 | 29.65 | 29.82 | 1.35 | **41.55** | 24.1 |
| 2d106det (192×192) | 2.30 | 7.24 | 7.31 | 0.11 | **9.65** | 103.6 |
| w600k_mbf (ArcFace 112×112) | 0.18 | 14.59 | 14.65 | 0.06 | **14.83** | 67.4 |
| minifasnet_v2_2.7 (80×80) | 0.37 | 5.11 | 5.21 | 0.08 | **5.56** | 180.0 |
| minifasnet_v1se_4.0 (80×80) | 0.37 | 5.75 | 5.89 | 0.08 | **6.20** | 161.2 |
| **Tổng (mọi model chạy 1 lần/frame)** | 13.8 | 62.3 | | 1.7 | **77.8** | **12.9 FPS** |

- Tiền xử lý của detector đo trên ảnh fixture 512×512; với khung 1080p thật thì letterbox tốn thêm khoảng 2.8 ms (đo riêng).
- Hậu xử lý của detector (decode anchor + NMS) là 1.32 ms, các model còn lại không đáng kể.
- So sánh: `trtexec` báo 25.6 ms cho det_500m, `TrtBackend` đo 29.1 ms. Chênh lệch là chi phí copy host↔device và đồng bộ stream trong đường dẫn Python.

## 2. Tối ưu đã áp dụng: tiền xử lý
Bản numpy đầu tiên của `common/imgproc.py::to_blob` tốn **22.4 ms** cho tensor 640×640 vì đi qua nhiều lần sao chép mảng (đổi kênh, ép kiểu, trừ, chia, chuyển trục). `cv2.dnn.blobFromImage` làm cùng việc đó trong một lượt C++:

| Cách làm | 640×640 | Kết quả |
|---|---|---|
| numpy | 22.42 ms | – |
| `cv2.dnn.blobFromImage` | **7.14 ms** | giống hệt từng bit khi `std` là luỹ thừa của 2 |

`to_blob` nay dùng OpenCV, giữ bản numpy làm dự phòng khi OpenCV không có module `dnn`. Với ArcFace (`std = 127.5`) hai cách lệch nhau 1 ulp (6e-8) vì OpenCV nhân `1/std` còn numpy chia `std`; test đã ghi nhận điều này.

**Ảnh hưởng:** tổng thời gian giảm từ 91.0 ms xuống 77.5 ms, tức từ 11.0 lên 12.9 FPS.

## 3. Bộ nhớ

| Phép đo | Giá trị |
|---|---|
| RSS đỉnh khi nạp **cả 5 engine** (`tests/device/test_engine_memory.py`) | **1024 MB** |
| RSS đỉnh của tiến trình benchmark (gồm ảnh, buffer, numpy) | 1400 MB |
| RAM toàn hệ thống lúc benchmark (tegrastats, có cả desktop) | 3139 / 3956 MB |
| Ngân sách cho tiến trình engine theo spec | 2.0–2.6 GB |

→ Còn rất nhiều chỗ trống. **D-16 (gộp 2 MiniFASNet thành 1 engine) là không cần thiết**: giữ 5 engine riêng cho đơn giản.

## 4. Độ chính xác FP16 so với ONNX FP32
`tests/device/test_trt_parity.py` — 9 test pass (2 ảnh test × 4 nhóm model + smoke test bộ nhớ):

| Model | Tiêu chí | Kết quả |
|---|---|---|
| SCRFD | cùng số mặt, IoU ≥ 0.95, lệch score < 0.05, lệch kps ≤ 2 px | đạt |
| 2d106det | lệch ≤ 1 px | đạt |
| ArcFace | cosine ≥ 0.99 | đạt |
| MiniFASNet | cùng argmax, lệch softmax ≤ 0.02 | đạt |

FP16 không làm đổi lớp của anti-spoof trên các mẫu thử.

## 5. Ý nghĩa cho pipeline (đầu vào cho M3)
Ngân sách một frame chạy **đủ** S1–S7 là 77.5 ms (12.9 FPS), chưa tính thu hình, IQA, ghi SQLite và tiến trình kiosk chạy song song. Spec yêu cầu 10–15 FPS, nên mức này đạt nhưng không dư.

Các hướng giảm tải, xếp theo thứ tự nên thử ở M3:
1. **Gate S3 đã giúp sẵn:** frame lệch mặt không gọi S4, tiết kiệm 13 ms.
2. **Không chạy S4 trên mọi frame:** ví dụ chỉ chạy trên các frame được S8 chọn, hoặc 1 lần mỗi N frame. Cần cân nhắc rủi ro bảo mật, và phải được duyệt (liên quan D-30).
3. **S5 và S7 chỉ chạy khi frame qua hết các gate trước** — đã nằm trong thiết kế engine loop.
4. **det_500m là phần nặng nhất (40.75 ms).** Có thể chạy detector ở nhịp thấp hơn và bám theo bbox giữa hai lần phát hiện, nhưng việc này thêm logic tracking; chỉ làm nếu đo ở M3 cho thấy cần.

## 6. Công suất và nhiệt độ
`tegrastats` chỉ in các rail `POM_*` khi chạy bằng root. Máy đã được cấp quyền sudo **giới hạn đúng một lệnh** (`/etc/sudoers.d/edgeface-tegrastats`, quyết định C-14), nên `bench_model.py --tegrastats --tegrastats-sudo` đọc được đầy đủ.

Đo trong lúc benchmark cả 5 model:

| Rail | Trung bình | Đỉnh |
|---|---|---|
| POM_5V_IN (toàn máy) | **5 468 mW** | 7 120 mW |
| POM_5V_GPU | 1 914 mW | 3 690 mW |
| POM_5V_CPU | 1 080 mW | 1 748 mW |

Nhiệt độ đỉnh: CPU 42.0 °C, GPU 40.5 °C, thermal 41.0 °C — chưa tới ngưỡng throttle. GPU trung bình 48%, CPU tổng 95% (gần một lõi rưỡi trong bốn lõi).

Nguồn micro-USB 5 V/2 A (10 W) không đủ an toàn ở mức đỉnh 7 W cộng thêm camera và ngoại vi; phải dùng jack tròn 5 V/4 A.

### 6.1 Hai yếu tố làm số đo dao động: `jetson_clocks` và điều kiện build engine

**Đính chính:** bản trước của tài liệu này quy toàn bộ chênh lệch cho `jetson_clocks`. Đo kỹ lại cho thấy có **hai** nguyên nhân tách biệt, và nguyên nhân lớn hơn nằm ở lúc build engine.

| Lần đo | ArcFace p50 | Tổng 5 model |
|---|---|---|
| Engine build lúc máy rảnh, có `jetson_clocks` | **14.59 ms** | **77.8 ms (12.9 FPS)** |
| Engine build lúc máy tải nặng, có `jetson_clocks` | 18.41 ms | 81.3 ms (12.3 FPS) |
| Engine build lúc máy tải nặng, không `jetson_clocks` | 18.44 ms | 81.8 ms (12.2 FPS) |

1. **Điều kiện build engine (≈ 4 ms/frame).** TensorRT chọn tactic bằng cách *đo thử* từng phương án ngay lúc build. Nếu máy đang tải nặng, phép đo bị nhiễu và nó chọn nhầm tactic chậm hơn. Cùng một lệnh `trtexec`, cùng file ONNX: log build lúc máy tải nặng ghi 18.08 ms, lúc máy rảnh ghi 14.24 ms. **Luôn build engine trên máy rảnh** (đăng xuất phiên đồ hoạ, không chạy song song việc khác), và kiểm tra con số mà `trtexec` in ra ở cuối mỗi lần build.
2. **`jetson_clocks` (ảnh hưởng tới độ ổn định, không phải tốc độ trung bình).** p50 gần như không đổi, nhưng độ tản thì khác hẳn: p95 của S1 trong pipeline giảm từ 71.4 ms xuống 40.8 ms, tức gần sát p50. `nvpmodel` giữ nguyên sau khi khởi động lại còn `jetson_clocks` thì không, nên phải chạy lại sau mỗi lần reboot, trước mỗi lần đo.

## 7. Trạng thái tiêu chí hoàn thành M2
- [x] `docs/device_inventory.md` có phiên bản thực tế
- [x] 5 engine FP16 build thành công, không commit vào git
- [x] `tests/device` pass với ngưỡng trong plan §6
- [x] Bảng latency + RAM (mục 1 và 3)
- [x] Công suất: 5.47 W trung bình, đỉnh 7.12 W (mục 6)
- [x] `vermin --target=3.6-` sạch cho code mới; `tests/unit` (29 test) pass ngay trên Nano
