# Kiểm kê thiết bị (M2-T01)

Ghi ngày **2026-09-21** trên máy thật. Mọi quyết định kỹ thuật của M2–M9 dựa trên bảng này.
Chạy lại bằng khối lệnh trong `docs/plans/M2_tensorrt_nano.md` §3 (M2-T01).

## Phần cứng
| Mục | Giá trị |
|---|---|
| Board | NVIDIA Jetson Nano Developer Kit |
| L4T / JetPack | R32.7.1 (JetPack 4.6.1), GCID 29818004, 2022-02-19 |
| Kernel | 4.9.253-tegra |
| RAM | 3956 MB tổng (chia sẻ CPU/GPU) |
| Swap | **chỉ zram**: 4 × 494 MB (chưa có swapfile trên đĩa) |
| Ổ đĩa | thẻ nhớ 30 GB, còn trống 16 GB |
| Camera | **Webcam USB "UGREEN Camera 2K"** trên `/dev/video0` (không phải CSI) |
| Truy cập | SSH `nano` → `js@192.168.0.17`, đăng nhập bằng khoá |

## Phần mềm
| Gói | Phiên bản | Ghi chú |
|---|---|---|
| Python | 3.6.9 | hệ thống |
| TensorRT | 8.2.1.8 (`libnvinfer8` 8.2.1-1+cuda10.2) | `trtexec` ở `/usr/src/tensorrt/bin/trtexec` |
| numpy | 1.13.3 (apt) | rất cũ: tránh API mới hơn 1.13 |
| OpenCV | 4.1.1 | **không có CUDA** (`cv2.cuda.getCudaEnabledDeviceCount() == 0`); **có GStreamer 1.14.5** |
| SQLite | 3.22.0 | không có UPSERT / window function (ràng buộc cho M4) |
| PyYAML | 3.12 (apt) | |
| PyQt5 | 5.10.1 (apt) | dùng cho kiosk M6 |
| pytest | 7.0.1 (pip --user) | bản cuối hỗ trợ Python 3.6 |
| pycuda | đang cài | phải dùng `--no-build-isolation`, xem §"Vấn đề đã gặp" |

## Kết quả đo ban đầu

### Engine TensorRT FP16 (từ log `trtexec`, GPU-only)
| Model | mean | median | p99 |
|---|---|---|---|
| det_500m | 25.64 ms | 25.64 ms | 25.78 ms |
| w600k_mbf | 14.09 ms | 14.07 ms | 14.12 ms |
| 2d106det | 6.33 ms | 6.34 ms | 6.38 ms |
| minifasnet_v1se_4.0 | 6.32 ms | 6.30 ms | 6.69 ms |
| minifasnet_v2_2.7 | 5.25 ms | 5.23 ms | 6.05 ms |
| **Tổng nếu chạy đủ 5 model/frame** | **57.6 ms** | | **≈ 17 FPS (chỉ GPU)** |

Cả 5 engine build thành công, **kể cả 2 MiniFASNet** — rủi ro `BatchNormalization` 1 chiều không xảy ra.

### Camera (OpenCV + V4L2)
| Định dạng | Độ phân giải | FPS đo được |
|---|---|---|
| MJPG | 1920×1080 | 14.9 |
| MJPG | 1280×720 | 14.9 |
| YUYV | 1280×720 | 9.1 |

→ Dùng MJPG. Vì 1080p không chậm hơn 720p, đề xuất giữ 1080p trong ring buffer (D-12).

### Test
`python3 -m pytest tests/unit` → **29 passed** trên thiết bị (numpy 1.13.3, OpenCV 4.1.1). Không có lỗi tương thích.

## Vấn đề đã gặp
1. **`pip install pycuda` thất bại** với thông báo cuối là "No matching distribution found". Nguyên nhân thật nằm sâu trong log: pip tạo môi trường build cách ly và cố biên dịch numpy 1.12.1 từ nguồn, nhưng numpy 1.12 không build được trên glibc của Ubuntu 18.04 (`fatal error: xlocale.h: No such file or directory`).
   **Cách xử lý:** `python3 -m pip install --user --no-build-isolation pycuda==2021.1` để dùng numpy 1.13.3 của hệ thống. `scripts/setup_nano.sh` đã được sửa theo cách này.
2. **CLAUDE.md ghi sai** rằng OpenCV của JetPack có CUDA. Đã sửa theo kết quả đo.
3. **Chưa có swapfile trên đĩa**, chỉ có zram. Build engine vẫn chạy được, nhưng nên tạo swap trước khi chạy đồng thời nhiều tiến trình (`scripts/setup_nano.sh --swap-gb 4`).

## Ảnh hưởng tới các quyết định
- **C-10, C-11, C-12** trong `docs/plans/decisions.md` được chốt từ bảng này.
- **D-12** (1080p hay 720p) có số liệu, chờ bạn xác nhận.
- **M4:** SQLite 3.22 nên không dùng được UPSERT — đúng như plan đã dự phòng.
- **S0/S5:** OpenCV không có CUDA nên resize/warp chạy trên CPU. Cần theo dõi latency pre-process ở M3.
