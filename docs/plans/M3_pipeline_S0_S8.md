# M3 — Pipeline S0–S8 + engine loop + chạy video offline

**Trạng thái:** Chưa bắt đầu · **Tuần:** 3 · **Phụ thuộc:** M1 (chạy x86), M2 (chạy Nano) · **Cần Nano:** Một phần

## 1. Mục tiêu và đầu ra
- Hiện thực stage S0–S8, mỗi stage là hàm thuần trả về `StageResult`.
- Có `engine/loop.py` điều phối stage theo từng khung hình, dừng sớm khi một gate fail.
- Có `scripts/run_pipeline_offline.py` chạy trên video ghi sẵn. Đầu ra: log gate theo từng frame, embedding thu được, và bảng latency từng stage + p50/p95 end-to-end + FPS.
- Chạy được trên x86 (`OrtBackend`) và trên Nano (`TrtBackend`) với cùng một code.

## 2. Phạm vi
- **Làm:** S0–S8, engine loop (chưa có session), `run_pipeline_offline`, instrument latency, công cụ trực quan hoá để debug.
- **Không làm:** S9/S10, state machine phiên, database (thuộc M4/M5), UI.

## 3. Thứ tự thực hiện và plan chi tiết từng stage

| Thứ tự | Stage | Plan | Mã task |
|---|---|---|---|
| 1 | Nền tảng: `FaceObs`, `pipeline/base.py`, orchestration | §5 dưới đây | M3-T01..T03 |
| 2 | S0 capture | [stages/S0_capture.md](stages/S0_capture.md) | M3-T10 |
| 3 | S1 detect | [stages/S1_detect.md](stages/S1_detect.md) | M3-T11 |
| 4 | S2 subject | [stages/S2_subject.md](stages/S2_subject.md) | M3-T12 |
| 5 | S3 coarse pose | [stages/S3_coarse_pose.md](stages/S3_coarse_pose.md) | M3-T13 |
| 6 | S4 anti-spoof | [stages/S4_antispoof.md](stages/S4_antispoof.md) | M3-T14 |
| 7 | S5 landmark + IQA | [stages/S5_landmark_iqa.md](stages/S5_landmark_iqa.md) | M3-T15 |
| 8 | S6 align | [stages/S6_align.md](stages/S6_align.md) | M3-T16 |
| 9 | S7 embed | [stages/S7_embed.md](stages/S7_embed.md) | M3-T17 |
| 10 | S8 best-frame | [stages/S8_best_frame.md](stages/S8_best_frame.md) | M3-T18 |
| 11 | Engine loop + offline runner + viz | §5–§6 | M3-T20..T23 |

## 4. Công việc

| Mã | Công việc |
|---|---|
| M3-T01 | Bổ sung `types.py`: `FaceObs` (namedtuple gom kết quả của một mặt qua các stage: `frame_id, ts, det, pose_coarse, spoof, lmk106, pose_fine, iqa, aligned, embedding, quality`); `GuidanceCode` (các hằng chuỗi: `NO_FACE`, `STEP_CLOSER`, `MOVE_TO_CENTER`, `LOOK_STRAIGHT`, `HOLD_STILL`, `TOO_DARK`, `TOO_BRIGHT`, `SPOOF_SUSPECT`) |
| M3-T02 | `pipeline/base.py`: helper `ok(data)`, `fail(reason, data=None)`; reason dùng `GuidanceCode` hoặc `Decision` |
| M3-T03 | `engine/models.py`: `load_models(cfg)` đọc `models.*` + manifest, tạo 5 wrapper qua `create_backend(cfg.backend, ...)`; kiểm tra sha256 của ONNX (dev) hoặc sidecar `.engine.json` (Nano) |
| M3-T10..T18 | Theo plan từng stage |
| M3-T20 | `engine/loop.py`: `process_frame(frame, models, cfg, collector) -> FrameOutcome(guidance, obs, collector_state)`. Không chứa ngưỡng hay phép tính; chỉ gọi stage theo thứ tự và dừng ở gate fail đầu tiên |
| M3-T21 | `scripts/run_pipeline_offline.py --config configs/dev.yaml --video path.mp4 [--realtime] [--out out_dir]`. `--realtime` bỏ frame theo đồng hồ để mô phỏng camera 15 FPS; mặc định xử lý mọi frame. Ghi `frames.csv` (frame_id, gate dừng, reason, latency từng stage), `embeddings.npz`, `summary.md` |
| M3-T22 | `tools/viz/overlay.py` (dev): vẽ bbox, 5 kps, 106 điểm, ROI, yaw/pitch/roll, p_real, blur, lum lên video để kiểm tra bằng mắt |
| M3-T23 | Instrument: mọi stage bọc `@timed("S1")`...; thêm `timed("e2e")` quanh `process_frame`; FPS đo bằng số frame hoàn tất / thời gian |

## 5. Thiết kế engine loop
```
frame (S0) ─► S1 detect ──0 mặt──► guidance NO_FACE, collector.reset_if_idle()
               │
               ▼
             S2 subject ──fail──► STEP_CLOSER / MOVE_TO_CENTER
               │
               ▼
             S3 coarse pose ──fail──► LOOK_STRAIGHT   (không gọi S4 để tiết kiệm GPU)
               │
               ▼
             S4 anti-spoof ──fail──► SPOOF_SUSPECT (lưu evidence ở M5; M3 chỉ ghi log)
               │
               ▼
             S5 landmark + IQA ──fail──► HOLD_STILL / TOO_DARK / TOO_BRIGHT / LOOK_STRAIGHT
               │
               ▼
             S6 align ─► S7 embed ─► S8 collector.add(embedding, quality)
                                          │
                                          ▼
                              đủ K hoặc hết cửa sổ ─► CollectorResult (ok | low_quality)
```
- **Một mặt mỗi frame:** chỉ mặt được S2 chọn đi tiếp.
- **Nối tiếp một luồng:** GPU chỉ có một nên không chạy song song các model; thread capture chạy riêng.
- **Frame dùng cho S4/S5/S6:** khung đầy đủ trong ring buffer (độ phân giải theo D-12), không phải ảnh letterbox 640.
- **Toạ độ:** mọi bbox/kps sau S1 ở hệ toạ độ khung đầy đủ.

## 6. Kiểm thử và đo lường
- **Unit:** mỗi stage có test riêng (xem plan stage), tất cả dùng numpy + ảnh tổng hợp, không cần model.
- **Tích hợp (`ort`):** `tests/integration/test_pipeline_video.py` chạy 1 video ngắn (≤ 10 s, người tình nguyện có phiếu đồng ý hoặc video tự quay, **không commit video**). Assert:
  - có ≥ 3 embedding hợp lệ khi người đứng thẳng;
  - khung chỉ có nền trả `NO_FACE`;
  - ảnh in trả `SPOOF_SUSPECT` (khi đã có ảnh tấn công mẫu từ M8).
- **Đo lường:** `summary.md` gồm bảng latency từng stage (mean/p50/p95), e2e p50/p95, FPS, tỉ lệ dừng ở từng gate. Trên Nano thêm RAM đỉnh + công suất (tegrastats).
- **Ngân sách thời gian:** chưa đặt con số; số liệu M2 là cơ sở để đặt ở bản cập nhật của plan này.

## 7. Giá trị cần xác nhận
D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-12, D-15 (chi tiết trong từng plan stage và `decisions.md`).

## 8. Tiêu chí hoàn thành
- [ ] 9 stage có test unit pass, `vermin` sạch
- [ ] `run_pipeline_offline.py` chạy trên x86 với video mẫu, xuất đủ 3 file đầu ra
- [ ] Chạy trên Nano (sau M2) và có `docs/results/M3_pipeline_perf.md`
- [ ] Không có ngưỡng nào hardcode (grep số thực trong `pipeline/` chỉ còn hằng toán học / template)

## 9. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Chuyển BGRx→BGR 1080p trên CPU làm tụt FPS | Đo ở S0; dùng 720p hoặc `nvvidconv` resize trong pipeline GStreamer (D-12) |
| Công thức yaw từ 5 điểm lệch nhiều so với solvePnP | Hiệu chỉnh hệ số trên video có nhãn góc (S3) |
| Ngưỡng blur 60 phụ thuộc kích thước crop | Chốt D-11 trước khi hiệu chuẩn |
