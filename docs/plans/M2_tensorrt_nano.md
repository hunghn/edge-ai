# M2 — Dựng Jetson Nano + TensorRT FP16 + benchmark từng model

**Trạng thái:** Đang làm (có thiết bị từ 2026-09-21, SSH `nano` = js@192.168.0.17) · **Tuần:** 1–2 · **Phụ thuộc:** M1 · **Cần Nano:** Có

> **Cập nhật 2026-09-21:** M2-T01 (kiểm kê), M2-T03 (chép model) và M2-T04 (build 5 engine FP16) đã xong.
> M2-T06 (`fold_bn1d.py`) **không cần** vì MiniFASNet parse được. `tests/unit` (28 test) pass trên Nano.
> M2-T11 dùng lại `tests/fixtures/goldens.npz` sẵn có thay vì dump tensor thô (`dump_onnx_outputs.py` bị bỏ):
> so sánh ở mức đầu ra của wrapper (bbox/kps/landmark/embedding/softmax) vừa nhỏ gọn vừa sát với pipeline.

## 1. Mục tiêu và đầu ra
Đạt đầu ra tuần 1–2 của spec §6:
- Thiết bị chạy được "hello world TensorRT".
- **Bảng latency cho từng model riêng lẻ**, kèm RAM và công suất.
- Engine FP16 cho cả 5 model, khớp số học với ONNX FP32.

## 2. Phạm vi
- **Làm:** script cài đặt thiết bị, build engine, `TrtBackend`, parser tegrastats, script benchmark, test parity trên thiết bị.
- **Không làm:** ghép pipeline (M3) và INT8 (Maxwell không hỗ trợ).

## 3. Công việc

| Mã | Công việc | Chi tiết |
|---|---|---|
| M2-T01 | Kiểm kê thiết bị | Ghi lại phiên bản thực tế: `cat /etc/nv_tegra_release`, `dpkg -l \| grep -E "tensorrt\|opencv\|cuda"`, `python3 -c "import tensorrt,cv2,numpy;..."`, `cv2.getBuildInformation()` (có CUDA? có GStreamer?), `sqlite3 --version`. Lưu vào `docs/device_inventory.md` |
| M2-T02 | `scripts/setup_nano.sh` | apt: `python3-pip python3-dev libhdf5-dev python3-pyqt5 sqlite3`; build `pycuda` (cần `CPATH=/usr/local/cuda/include`, `PATH=/usr/local/cuda/bin:$PATH`); tạo swapfile 4 GB; `sudo nvpmodel -m 0` (MAXN 10 W); `sudo jetson_clocks`; tạo `/var/lib/edgeface` với quyền cho user service. Script idempotent (chạy lại không lỗi) |
| M2-T03 | Chép model | `rsync models/onnx/*.onnx models/manifest.yaml` lên Nano; `scripts/verify_models.py` so sha256 với manifest |
| M2-T04 | `scripts/build_engines.sh` | Với mỗi model: `/usr/src/tensorrt/bin/trtexec --onnx=models/onnx/X.onnx --fp16 --workspace=1024 --saveEngine=models/engines/X.engine --verbose > logs/build_X.log`. Ghi thêm `X.engine.json` (sha256 ONNX nguồn, phiên bản TensorRT, ngày build) để phát hiện engine cũ |
| M2-T05 | Kiểm tra FP16 | Với mỗi engine: chạy `trtexec --loadEngine` và xem có layer nào bị ép về FP32 hay không |
| M2-T06 | Xử lý BatchNorm1d của MiniFASNet (nếu parse lỗi) | Thêm `tools/convert/fold_bn1d.py`: gộp `BatchNormalization` sau `MatMul` vào trọng số Linear (W' = W·γ/σ, b' = (b−μ)·γ/σ + β), rồi chạy lại parity trên máy dev |
| M2-T07 | `src/edgeface/runtime/trt_backend.py` | TensorRT 8.2 binding API: `trt.Runtime(logger).deserialize_cuda_engine`, `engine.num_bindings`, `get_binding_name/shape/dtype`, `binding_is_input`; cấp phát `pycuda.driver.pagelocked_empty` cho host và `mem_alloc` cho device; `execute_async_v2` + `stream.synchronize()`. Trả `OrderedDict` giống `OrtBackend`. Kiểm tra dtype và shape input, copy đúng thứ tự `np.ascontiguousarray` |
| M2-T08 | Chia sẻ CUDA context | Một `pycuda` context duy nhất cho cả 5 engine trong cùng tiến trình (`cuda.Device(0).make_context()` hoặc `pycuda.autoinit` ở entry point); `close()` giải phóng đúng thứ tự |
| M2-T09 | `src/edgeface/metrics/tegrastats.py` | Chạy `tegrastats --interval 500` bằng `subprocess.Popen`, parse `RAM a/bMB`, `CPU [x%@f,...]`, `GR3D_FREQ y%`, `POM_5V_IN cur/avg`, `POM_5V_GPU`, `POM_5V_CPU`, nhiệt độ. Regex có unit test với chuỗi mẫu |
| M2-T10 | `scripts/bench_model.py` | `--model X \| --all`, `--warmup 50 --iters 500`; đo riêng pre-process, infer và post-process; ghi CSV + in bảng Markdown (mean, p50, p95, max ms, FPS tương đương); ghi RAM tiến trình (`/proc/self/status` VmRSS) và RAM hệ thống từ tegrastats |
| M2-T11 | `tests/device/test_trt_parity.py` (marker `nano`) | Dump golden ONNX FP32 trên máy dev (`tools/convert/dump_onnx_outputs.py` → `tests/fixtures/onnx_outputs.npz`); trên Nano so với engine FP16 |
| M2-T12 | Smoke test RAM | Nạp đồng thời cả 5 engine trong một tiến trình, ghi RAM đỉnh, so với ngân sách 2.0–2.6 GB của tiến trình engine |
| M2-T13 | Báo cáo | `docs/results/M2_latency.md`: bảng latency, RAM, công suất, phiên bản phần mềm, chế độ nguồn |

## 4. File tạo/sửa
- `scripts/setup_nano.sh`, `scripts/build_engines.sh`, `scripts/verify_models.py`, `scripts/bench_model.py`
- `src/edgeface/runtime/trt_backend.py`, `src/edgeface/metrics/{__init__,tegrastats}.py`
- `tests/device/test_engine_memory.py` (M2-T12)
- `tests/device/test_trt_parity.py`, `tests/unit/test_tegrastats_parse.py`
- `docs/device_inventory.md` (đã có), `docs/results/M2_latency.md`
- Bỏ khỏi kế hoạch: `tools/convert/dump_onnx_outputs.py` và `tools/convert/fold_bn1d.py` (xem cập nhật đầu file)

## 5. Thiết kế chi tiết: `TrtBackend`
```
TrtBackend(path)
  ├─ load engine (đọc bytes → deserialize)
  ├─ for i in bindings: name, shape (tĩnh), dtype = trt.nptype(...)
  │     host = cuda.pagelocked_empty(volume, dtype); dev = cuda.mem_alloc(host.nbytes)
  ├─ inputs / outputs → list[TensorSpec]
  └─ infer(feeds):
        np.copyto(host_in, feeds[name].ravel())   # kiểm tra shape trước
        cuda.memcpy_htod_async(dev_in, host_in, stream)
        context.execute_async_v2(bindings, stream.handle)
        cuda.memcpy_dtoh_async(host_out, dev_out, stream); stream.synchronize()
        return OrderedDict(name → host_out.reshape(shape).copy())
```
- Output FP16 nội bộ vẫn trả dtype `float32` (binding I/O giữ float32 khi build bằng `--fp16`).
- Không dùng `set_tensor_address` / `execute_async_v3`: đó là API của TensorRT ≥ 8.5.

## 6. Giá trị cần xác nhận
- ~~D-13: loại camera~~ → đã chốt C-12: webcam USB, MJPG 1080p @ 15 FPS.
- **D-16:** gộp 2 MiniFASNet hay không. Quyết sau khi có số RAM ở M2-T12.
- **Ngưỡng parity FP16** (đề xuất, chờ duyệt cùng plan này):

| Model | Tiêu chí |
|---|---|
| ArcFace | cosine(FP16, FP32) ≥ 0.99 |
| MiniFASNet | Lệch softmax ≤ 0.02 và cùng argmax |
| SCRFD | Cùng số mặt trên ảnh test; IoU ≥ 0.95 |
| 2d106det | Lệch ≤ 1 px |

## 7. Kiểm thử và đo lường
- `pytest tests/unit tests/device -m "not ort"` trên Nano.
- `python3 scripts/bench_model.py --all`, chạy ở cả chế độ 10 W và 5 W, ghi rõ chế độ trong báo cáo.
- Theo dõi nhiệt độ: nếu vượt ngưỡng throttle trong lúc bench, ghi chú lại và gắn quạt.

## 8. Tiêu chí hoàn thành
- [ ] `docs/device_inventory.md` có phiên bản thực tế
- [ ] 5 engine build thành công; `.engine` không bị commit
- [ ] `tests/device` pass với ngưỡng ở §6
- [ ] `docs/results/M2_latency.md` có bảng latency (p50/p95), RAM đỉnh khi nạp đủ 5 engine, công suất
- [ ] `vermin` sạch cho các file mới

## 9. Rủi ro
| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| OpenCV của JetPack 4.6 có thể **không** được build với CUDA (CLAUDE.md đang ghi là có) | Resize/warp chạy trên CPU | Kiểm chứng ở M2-T01; nếu không có CUDA thì chấp nhận CPU (ảnh nhỏ) hoặc resize bằng `nvvidconv` trong GStreamer |
| `pycuda` build lỗi trên Python 3.6 | Không có TrtBackend | Pin phiên bản 2021.1, hoặc dùng `cuda-python` / ctypes với `libcudart` |
| BatchNorm1d không parse | Mất anti-spoof | M2-T06 |
| Thiếu RAM khi build engine | `trtexec` bị kill | Tạo swap, build từng engine, giảm `--workspace` |
| Numpy 1.13 của apt quá cũ cho code hiện tại | Lỗi runtime | Chạy `tests/unit` trên Nano ngay ở M2; sửa chỗ dùng API mới |
