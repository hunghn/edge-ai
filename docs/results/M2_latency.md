# M2 — Kết quả đo latency từng model trên Jetson Nano

**Ngày đo:** 2026-09-21 · **Thiết bị:** xem [`docs/device_inventory.md`](../device_inventory.md)
**Chế độ nguồn:** nvpmodel mode 0 (MAXN 10 W), `jetson_clocks` · **Precision:** FP16 · **Batch:** 1

Tái lập:
```bash
ssh nano 'cd ~/edge-ai && python3 scripts/bench_model.py --all --warmup 30 --iters 200 --tegrastats --csv bench.csv'
```

## 1. Latency từng model (p50, ms)

| Model | Tiền xử lý | Suy luận | Suy luận p95 | Hậu xử lý | Tổng | ~FPS nếu chạy riêng |
|---|---|---|---|---|---|---|
| det_500m (SCRFD 640×640) | 10.36 | 29.07 | 29.31 | 1.32 | **40.75** | 24.5 |
| 2d106det (192×192) | 2.12 | 6.78 | 6.84 | 0.10 | **9.01** | 111.0 |
| w600k_mbf (ArcFace 112×112) | 0.18 | 14.39 | 14.45 | 0.06 | **14.63** | 68.4 |
| minifasnet_v2_2.7 (80×80) | 0.37 | 5.61 | 5.76 | 0.07 | **6.06** | 165.1 |
| minifasnet_v1se_4.0 (80×80) | 0.37 | 6.57 | 6.77 | 0.07 | **7.01** | 142.7 |
| **Tổng (mọi model chạy 1 lần/frame)** | 13.4 | 62.4 | | 1.6 | **77.5** | **12.9 FPS** |

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

Đo trong lúc benchmark cả 5 model (lần chạy `schedutil`, xem §6.1):

| Rail | Trung bình | Đỉnh |
|---|---|---|
| POM_5V_IN (toàn máy) | **5 259 mW** | 7 043 mW |
| POM_5V_GPU | 1 780 mW | 3 429 mW |
| POM_5V_CPU | 1 026 mW | 1 711 mW |

Nhiệt độ đỉnh: CPU 43.5 °C, GPU 43.0 °C, thermal 42.5 °C — chưa tới ngưỡng throttle. GPU trung bình 56%, CPU tổng 95% (gần một lõi rưỡi trong bốn lõi).

Nguồn micro-USB 5 V/2 A (10 W) không đủ an toàn ở mức đỉnh 7 W cộng thêm camera và ngoại vi; phải dùng jack tròn 5 V/4 A.

### 6.1 Ảnh hưởng của `jetson_clocks` — lưu ý khi đo lại
`nvpmodel` giữ nguyên sau khi khởi động lại, nhưng **`jetson_clocks` thì không**. Sau một lần reboot, governor trở lại `schedutil` và số đo chậm đi rõ rệt:

| Model | Với `jetson_clocks` | Sau reboot (`schedutil`) |
|---|---|---|
| det_500m | 40.75 ms | 41.66 ms |
| 2d106det | 9.01 ms | 9.51 ms |
| w600k_mbf | **14.63 ms** | **18.68 ms** |
| minifasnet_v2_2.7 | 6.06 ms | 5.63 ms |
| minifasnet_v1se_4.0 | 7.01 ms | 6.29 ms |
| **Tổng** | **77.5 ms (12.9 FPS)** | **81.8 ms (12.2 FPS)** |

Chênh lệch tập trung ở ArcFace (+28%). Vì vậy quy trình đo chuẩn phải chạy `sudo jetson_clocks` **ngay trước** mỗi lần benchmark, và báo cáo luôn ghi rõ trạng thái xung nhịp. Bảng ở §1 là số liệu có `jetson_clocks`.

## 7. Trạng thái tiêu chí hoàn thành M2
- [x] `docs/device_inventory.md` có phiên bản thực tế
- [x] 5 engine FP16 build thành công, không commit vào git
- [x] `tests/device` pass với ngưỡng trong plan §6
- [x] Bảng latency + RAM (mục 1 và 3)
- [x] Công suất: 5.26 W trung bình, đỉnh 7.04 W (mục 6)
- [x] `vermin --target=3.6-` sạch cho code mới; `tests/unit` (29 test) pass ngay trên Nano
