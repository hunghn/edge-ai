# M5 — Engine session: S9/S10, luồng nhận dạng và luồng enrollment

**Trạng thái:** Chưa bắt đầu · **Tuần:** 3–4 · **Phụ thuộc:** M3 (S0–S8), M4 (storage) · **Cần Nano:** Không (chạy video trên x86)

## 1. Mục tiêu và đầu ra
- Tiến trình `engine` hoàn chỉnh: `python3 -m edgeface.engine --config configs/<env>.yaml`.
- State machine phiên điều khiển pipeline, giao tiếp với kiosk qua `kiosk_state` / `kiosk_commands`, và ghi `sessions`, `outbox`, `evidence`.
- Hai luồng nghiệp vụ: **nhận dạng** (identify) và **đăng ký khuôn mặt** (enroll, C-01).
- Plan chi tiết của S9 và S10 nằm trong [stages/S9_match.md](stages/S9_match.md) và [stages/S10_decide.md](stages/S10_decide.md).

## 2. Phạm vi
- **Làm:** S9, S10, session, publisher, enroll, lưu evidence, retention scheduler, entrypoint + systemd unit cho engine, preview JPEG.
- **Không làm:** UI (M6), sync với server (M7).

## 3. State machine (`engine/session.py`)

```
                ┌───────────────────────── cancel / timeout ─────────────────────────┐
                ▼                                                                    │
  ┌──────┐ mặt hợp lệ ┌─────────┐ gate S1–S5 qua ┌────────────┐ READY ┌─────────┐    │
  │ IDLE │──────────►│ GUIDING │──────────────►│ COLLECTING │──────►│ DECIDED │    │
  └──────┘◄──────────└─────────┘◄──────────────└────────────┘       └────┬────┘    │
     ▲   NO_FACE > t_idle   ▲   SUBJECT_LOST/CHANGED     │ LOW_QUALITY     │ ghi      │
     │                      └────────────────────────────┘ → DECIDED       ▼ kiosk    │
     │                                                             ┌─────────────┐  │
     │        ┌──────────┐   confirm / reject / manual / timeout   │ AWAIT_NURSE │──┘
     └────────│ COOLDOWN │◄────────────────────────────────────────└─────────────┘
              └──────────┘         retry → GUIDING (phiên mới, attempt + 1)

  Lệnh start_enroll (từ màn quản trị, đã xác thực PIN) ở trạng thái IDLE/GUIDING
     → ENROLL_GUIDING → ENROLL_COLLECTING → ENROLL_REVIEW → (confirm) lưu → COOLDOWN
                                                        └→ (cancel)  huỷ  → IDLE
```
- **Hàm chuyển trạng thái thuần:** `transition(state, event, ctx, cfg) -> (new_state, actions)`. `actions` là danh sách lệnh (`publish`, `open_session`, `close_session`, `save_evidence`, `enqueue`, `reset_collector`), được `engine/loop.py` thực thi. Nhờ vậy state machine test được mà không cần DB hay model.
- **Sự kiện:** `FRAME_OUTCOME(guidance, collector_status)`, `NURSE_CMD(type, payload)`, `TICK(now)`.
- **Timeout:** `AWAIT_NURSE` → `nurse_action = timeout` → COOLDOWN; `COOLDOWN` → IDLE; màn quản trị tự khoá (D-21).
- **Khi ở AWAIT_NURSE / COOLDOWN:** engine **không chạy** S1–S8 (tiết kiệm GPU), chỉ cập nhật preview.

## 4. Luồng nhận dạng
1. IDLE → GUIDING khi S1 có mặt; `open_session(kind='identify')`.
2. Mỗi frame: `process_frame` (M3) → `guidance` → `publish_state` (chỉ ghi khi `guidance` đổi hoặc mỗi 500 ms, để giảm ghi đĩa).
3. S8 `READY` → S9 → S10 → DECIDED:
   - Lưu evidence nếu `spoof_suspect` (frame có `p_real` thấp nhất, theo D-14).
   - `publish_state(AWAIT_NURSE, payload={decision, rule_id, candidate{code, full_name, birth_year, appointment}, confidence_label})`.
4. Lệnh điều dưỡng:

| Lệnh | Payload | Xử lý |
|---|---|---|
| `confirm` | `{operator_id?, code}` | `nurse_action = confirm`, `confirmed_code = code` |
| `reject` | – | `nurse_action = reject` |
| `manual` | `{code}` | điều dưỡng chọn BN qua tìm kiếm; `nurse_action = manual` |
| `retry` | – | đóng phiên hiện tại (`retry`) và mở phiên mới |

5. `close_session(...)` + `enqueue('session.closed', {...không có embedding...})`. Nếu spoof thì thêm `enqueue('spoof.detected', {session_id, evidence_sha256, p_real})`.

## 5. Luồng enrollment (`engine/enroll.py`)
1. Kiosk (đã qua PIN) gửi `start_enroll {patient_code, full_name, birth_year, appointment_code, operator_id}`.
2. Engine kiểm tra:
   - mã BN chưa tồn tại, hoặc tồn tại với nguồn `kiosk` thì hỏi ghi đè
   - các trường bắt buộc có đủ
   - Sai → `publish_state(ENROLL_ERROR, reason)`.
3. `ENROLL_COLLECTING`: chạy đủ S1–S7 **gồm S4 anti-spoof** với cùng ngưỡng. Thu `N = enroll.num_templates` template (D-20) từ các frame khác nhau:
   - cách nhau ≥ `enroll.min_interval_s`
   - ưu tiên đa dạng nhẹ về pose trong giới hạn gate S5

   Tiến độ `k/N` được publish cho kiosk. Hết `enroll.timeout_s` mà chưa đủ → `ENROLL_ERROR(low_quality)`.
4. **Kiểm tra trùng:** so N template mới với gallery hiện tại (S9).
   - Nếu có BN khác có điểm ≥ `enroll.duplicate_threshold` → `ENROLL_REVIEW` với cảnh báo "khuôn mặt giống BN X". Chặn hẳn hay cho điều dưỡng xác nhận lần 2 tuỳ D-20.
   - Khi `duplicate_threshold` là `null`, **luôn** hiển thị top1 gần nhất để điều dưỡng tự đánh giá.
5. **Kiểm tra nhất quán nội bộ:** cosine trung bình giữa N template ≥ `enroll.self_consistency_min` (tránh lẫn hai người trong lúc chụp); `null` thì bỏ qua.
6. Điều dưỡng `confirm` → một giao dịch:
   - `upsert_patient(source='kiosk', expires_at = now + 24h)` + `upsert_appointment` + `add_templates(...)` + `bump_gallery_version()`
   - `enqueue('enrollment.created', {patient, appointment, templates: [base64 float32], recognizer_sha256, operator_id})`
7. Gallery được reload trước phiên nhận dạng kế tiếp.

## 6. Công việc

| Mã | Công việc |
|---|---|
| M5-T01 | `engine/session.py`: trạng thái, sự kiện, `transition` thuần + test bảng chuyển trạng thái |
| M5-T02 | `engine/publisher.py`: gom `publish_state` (debounce), đọc lệnh, ghi preview JPEG `/dev/shm/edgeface/preview.jpg` (C-09) ở `kiosk.preview_fps`, kích thước `kiosk.preview_width` |
| M5-T03 | `engine/loop.py` (mở rộng M3): vòng lặp chính gồm capture → process_frame → session.transition → thực thi actions; `TICK` mỗi vòng |
| M5-T04 | `engine/enroll.py`: collector enrollment + kiểm tra trùng/nhất quán |
| M5-T10 | S9 theo [stages/S9_match.md](stages/S9_match.md) |
| M5-T11 | S10 theo [stages/S10_decide.md](stages/S10_decide.md) |
| M5-T12 | Lưu evidence (D-14): crop/khung → JPEG → `storage/evidence.save` |
| M5-T13 | Retention scheduler: gọi `gallery/retention.run_once` mỗi `retention.interval_s` giữa các phiên |
| M5-T14 | Ghi `stage_latency` theo lô (mỗi phiên, hoặc mỗi 5 s khi IDLE thì bỏ) |
| M5-T15 | `engine/__main__.py`: nạp config, migrate DB, nạp model, bắt `SIGTERM` để dừng sạch (đóng phiên đang mở với `nurse_action = cancel`) |
| M5-T16 | `deploy/systemd/edgeface-engine.service` (`Restart=always`, `MemoryMax` theo ngân sách 2.6 GB, `After=nvargus-daemon.service`) |
| M5-T17 | `scripts/run_pipeline_offline.py --session`: chạy toàn bộ luồng trên video, lệnh điều dưỡng giả lập bằng `--auto-nurse confirm\|reject` |
| M5-T18 | `scripts/enroll_from_video.py` (dev): enroll từ video để chuẩn bị gallery test |

## 7. Config keys mới
`session.idle_after_s`, `session.await_nurse_timeout_s`, `session.cooldown_s` (D-21), `enroll.num_templates`, `enroll.min_interval_s`, `enroll.timeout_s`, `enroll.duplicate_threshold`, `enroll.duplicate_policy` (`block|confirm`), `enroll.self_consistency_min` (D-20), `retention.interval_s`, `kiosk.preview_fps`, `kiosk.preview_width`, `decision.spoof_rule` (D-30).

## 8. Giá trị cần xác nhận
D-01..D-04, D-14, D-20, D-21, D-30; các giá trị vận hành `enroll.min_interval_s`, `enroll.timeout_s`, `retention.interval_s`, `kiosk.preview_fps/width` (đề xuất sẽ trình khi bắt đầu M5).

## 9. Kiểm thử
- **Unit:** bảng chuyển trạng thái (mọi cặp trạng thái × sự kiện hợp lệ và không hợp lệ); enroll (đủ N, timeout, trùng, không nhất quán); publisher debounce.
- **Tích hợp (`ort`):** video A (người đã enroll) → phiên `identify`, S10 ra `review_required` (ngưỡng `null`), top1 đúng người; lệnh `confirm` giả → `sessions.nurse_action = confirm`, outbox có đúng 1 `session.closed`.
- **Tích hợp enroll:** `enroll_from_video` → `face_templates` có N dòng, `gallery_meta.version` tăng, outbox có `enrollment.created`.
- **Chịu lỗi:** kill -9 engine giữa phiên → khởi động lại → phiên dở được đóng với `cancel`, DB nhất quán.
- **Đo:** thời gian từ lúc đứng vào đến lúc hiện thẻ ứng viên (p50/p95); RAM tiến trình engine trên Nano ≤ 2.6 GB.

## 10. Tiêu chí hoàn thành
- [ ] Test unit và tích hợp pass
- [ ] Chạy liên tục 2 giờ trên video lặp không rò rỉ RAM (tăng < 5%)
- [ ] systemd unit hoạt động trên Nano
- [ ] Plan S9/S10 được cập nhật theo giá trị đã chốt

## 11. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Trộn embedding hai người trong một phiên | Tính liên tục ở S8 (D-31) + kiểm tra nhất quán khi enroll |
| Kiosk và engine lệch trạng thái | `seq` tăng dần, kiosk chỉ hiển thị theo `kiosk_state`; lệnh có `session_id` và bị bỏ qua nếu không khớp phiên hiện tại |
| Ghi đĩa quá nhiều | Debounce publish, metrics theo lô |
