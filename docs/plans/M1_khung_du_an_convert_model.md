# M1 — Khung dự án + chuyển đổi model (máy dev, x86)

**Trạng thái:** ✅ Hoàn thành 2026-09-17 · 35 test pass · `vermin --target=3.6-` sạch

## 1. Mục tiêu và đầu ra
- Có 5 file ONNX với input shape cố định, sẵn sàng build TensorRT trên Nano.
- Có `models/manifest.yaml` ghi nguồn, tiền xử lý và sha256 của từng model.
- Có wrapper numpy/OpenCV cho 4 loại model, chạy qua backend có thể thay thế được.
- Output của wrapper khớp số học với repo tham chiếu `ims_id_server`.

## 2. Phạm vi
- **Làm:** khung package `edgeface`, config, backend onnxruntime, wrapper SCRFD / MiniFASNet / 2d106det / ArcFace, S6 align (làm sớm vì test ArcFace cần), các tool convert, unit test và parity test.
- **Không làm:** TensorRT (thuộc M2), các stage S0–S5 và S7–S10 (M3, M5), database và UI.

## 3. Công việc đã thực hiện

| Mã | Công việc | Kết quả |
|---|---|---|
| M1-T01 | Tạo `.venv`, cài torch CPU, onnx, onnxruntime, onnxsim, pytest, vermin | torch 2.14 CPU, onnx 1.22, ort 1.30 |
| M1-T02 | `setup.py`, `requirements/{device,dev}.txt`, `pytest.ini`, bổ sung `.gitignore` | Package cài được bằng `pip install -e .` |
| M1-T03 | `configs/{default,dev,nano}.yaml` + `config.py` (deep-merge, validate, đóng băng bằng `MappingProxyType`) | Giá trị chưa chốt để `null` |
| M1-T04 | `types.py`: `Frame`, `Detection`, `StageResult`, `Embedding`, `Decision` | namedtuple, tương thích 3.6 |
| M1-T05 | `common/`: `geometry` (NMS, Umeyama, affine), `imgproc` (letterbox, to_blob, softmax), `timing` (`@timed`, p50/p95), `log` | |
| M1-T06 | `runtime/base.py`, `runtime/ort_backend.py`, factory `create_backend` | onnxruntime được import lazy |
| M1-T07 | `models/scrfd.py`: decode anchor, NMS, output nhận diện theo shape | Không phụ thuộc thứ tự binding |
| M1-T08 | `models/minifasnet.py`: port `CropImage`, input 0–255 BGR, softmax | |
| M1-T09 | `models/landmark106.py`: crop bbox×1.5 → 192, map [−1,1] ngược lại | |
| M1-T10 | `models/arcface.py`, `pipeline/align.py` (Umeyama thay cho skimage) | |
| M1-T11 | `tools/convert/fetch_insightface.py`: tải buffalo_sc/buffalo_l | det_500m, w600k_mbf, 2d106det |
| M1-T12 | `tools/convert/minifasnet_pth2onnx.py`: opset 11 + onnxsim | Lệch logits ≤ 3e-6 |
| M1-T13 | `tools/convert/fix_shapes.py`: shape tĩnh + onnxsim + ghi sha256 vào manifest | |
| M1-T14 | `tools/convert/onnx_parity.py` | Model gốc vs model cố định shape ≤ 2e-6; pth vs onnx ≤ 4e-6 |
| M1-T15 | `tests/parity/make_goldens.py` + `tests/fixtures/{astronaut.jpg, goldens.npz}` | Golden sinh từ code tham chiếu |
| M1-T16 | Unit test (geometry, SCRFD decode, CropImage, align, config) + parity test | 35 pass |

## 4. Kết quả parity (wrapper của ta so với repo tham chiếu)

| Model | Chỉ số | Kết quả |
|---|---|---|
| SCRFD det_500m | IoU bbox, lệch score, lệch kps | > 0.99; < 1e-4; < 0.05 px |
| 2d106det | Lệch toạ độ 106 điểm | < 0.05 px |
| S6 align | Lệch pixel ảnh crop (numpy Umeyama vs skimage) | ≤ 2 mức xám |
| ArcFace w600k_mbf | cosine giữa hai embedding | > 0.999 |
| MiniFASNet V2 / V1SE | Lệch xác suất softmax | < 1e-4 |
| CropImage | Ảnh crop trên 20 bbox ngẫu nhiên, kể cả bbox chạm biên | Trùng khớp từng pixel |

## 5. Phát hiện quan trọng (đã xử lý)
1. **Tensor đầu vào là RGB:** SCRFD, 2d106det và ArcFace đều dùng `swapRB=True`, nên tensor đưa vào mạng là RGB. MiniFASNet giữ BGR và không chia 255.
2. **Heuristic mean/std của repo tham chiếu hỏng sau onnxsim:** onnxsim gộp node `Mul` vào Conv đầu tiên của 2d106det, nên heuristic dò node Sub/Mul của `Landmark` chọn nhầm (127.5, 128). Đã chốt mean 0 / std 1 (C-06), và golden được sinh từ model **gốc**.
3. **Kích thước input của repo tham chiếu khác:** repo tham chiếu dùng letterbox SCRFD 320×320; dự án này dùng 640×640 theo spec.
4. **Rủi ro TensorRT:** cả 2 MiniFASNet có một `BatchNormalization` 1 chiều (sau Flatten). TensorRT 8.2 có thể không parse được, sẽ xử lý ở M2 (task M2-T06).

## 6. Cách tái lập
```bash
source .venv/bin/activate
python tools/convert/fetch_insightface.py
python tools/convert/minifasnet_pth2onnx.py
python tools/convert/fix_shapes.py
python tools/convert/onnx_parity.py
pytest tests/unit tests/parity
vermin --target=3.6- --violations src/ tests/unit/
```

## 7. Tiêu chí hoàn thành — đã đạt
- [x] 5 ONNX shape tĩnh, sha256 trong manifest
- [x] Parity với repo tham chiếu đạt các ngưỡng ở §4
- [x] `tests/unit` không import onnxruntime/torch
- [x] `vermin` sạch cho `src/` và `tests/unit/`
