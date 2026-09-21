# Kế hoạch triển khai — edge-ai

Thư mục này chứa plan chi tiết cho từng **milestone (phase)** và từng **stage S0–S10** của pipeline. Các file ở đây là nguồn chính cho việc thực hiện. Trước khi code một milestone, plan tương ứng phải được duyệt (xem Plan-First Policy trong `CLAUDE.md`).

- Spec gốc: `docs/pipeline_jetson_nano.docx`
- Hướng dẫn cho người đóng góp và agent: `CLAUDE.md`
- Cấu trúc thư mục đề xuất: `README.md` §2
- Sổ quyết định và các giá trị còn mở: [`decisions.md`](decisions.md)

## 1. Lộ trình

| Milestone | Nội dung | Cần Nano? | Phụ thuộc | Tuần (spec §6) | Trạng thái |
|---|---|---|---|---|---|
| [M1](M1_khung_du_an_convert_model.md) | Khung dự án, convert ONNX, wrapper model, parity test | Không | – | 1 | ✅ Xong |
| [M2](M2_tensorrt_nano.md) | Dựng Nano, build TensorRT engine, benchmark từng model | **Có** | M1 | 1–2 | Chờ thiết bị |
| [M3](M3_pipeline_S0_S8.md) | Pipeline S0–S8 + engine loop + chạy video offline | Một phần | M1 (M2 để chạy trên Nano) | 3 | Chưa bắt đầu |
| [M4](M4_database.md) | Database cục bộ SQLite WAL | Không | M1 | 3 | Chưa bắt đầu |
| [M5](M5_engine_session.md) | S9/S10, state machine phiên, luồng nhận dạng và enrollment | Không (dùng video) | M3, M4 | 3–4 | Chưa bắt đầu |
| [M6](M6_kiosk_ui.md) | Giao diện kiosk PyQt5 | Không (dùng `fake_engine`) | M4 | 4 | Chưa bắt đầu |
| [M7](M7_server_sync.md) | Server tối giản + tiến trình sync | Không | M4 | 4–5 | Chưa bắt đầu |
| [M8](M8_baseline_dataset.md) | Baseline Haar+LBPH, thu thập dataset | **Có** | M2, M3 | 3–5 | Chưa bắt đầu |
| [M9](M9_danh_gia.md) | Hiệu chuẩn ngưỡng, đánh giá, ablation, báo cáo | **Có** | M5–M8 | 6–7 | Chưa bắt đầu |

```
M1 ──► M2 ──────────────┐
 │                      ▼
 ├──► M3 (S0–S8) ──► M5 (S9–S10, session) ──► M9
 │                      ▲                     ▲
 └──► M4 (DB) ──┬───────┘                     │
                ├──► M6 (kiosk UI)            │
                └──► M7 (server + sync)       │
M2 + M3 ──► M8 (baseline + dataset) ──────────┘
```

Thứ tự đề xuất khi **chưa có Nano**: M4, rồi M3 (chạy trên x86 với `OrtBackend`), rồi làm song song M6 và M7, cuối cùng M5. Khi có Nano: M2, sau đó chạy lại M3 trên thiết bị, rồi M8 và M9.

## 2. Plan theo stage

| Stage | Plan | Milestone | Module chính |
|---|---|---|---|
| S0 capture | [S0_capture.md](stages/S0_capture.md) | M3 | `pipeline/capture.py` |
| S1 detect | [S1_detect.md](stages/S1_detect.md) | M3 | `pipeline/detect.py`, `models/scrfd.py` |
| S2 subject | [S2_subject.md](stages/S2_subject.md) | M3 | `pipeline/subject.py` |
| S3 coarse pose | [S3_coarse_pose.md](stages/S3_coarse_pose.md) | M3 | `pipeline/pose.py` |
| S4 anti-spoof | [S4_antispoof.md](stages/S4_antispoof.md) | M3 | `pipeline/antispoof.py`, `models/minifasnet.py` |
| S5 landmark + IQA | [S5_landmark_iqa.md](stages/S5_landmark_iqa.md) | M3 | `pipeline/pose.py`, `pipeline/quality.py`, `models/landmark106.py` |
| S6 align | [S6_align.md](stages/S6_align.md) | M3 | `pipeline/align.py` |
| S7 embed | [S7_embed.md](stages/S7_embed.md) | M3 | `pipeline/embed.py`, `models/arcface.py` |
| S8 best-frame | [S8_best_frame.md](stages/S8_best_frame.md) | M3 | `pipeline/best_frame.py` |
| S9 match | [S9_match.md](stages/S9_match.md) | M5 | `pipeline/matcher.py`, `gallery/gallery.py` |
| S10 decide | [S10_decide.md](stages/S10_decide.md) | M5 | `pipeline/decision.py` |

## 3. Khuôn mẫu của một plan

**Plan milestone** gồm:
1. Mục tiêu và đầu ra
2. Phạm vi (làm / không làm)
3. Phụ thuộc
4. Danh sách công việc có mã (ví dụ `M4-T03`)
5. File tạo/sửa
6. Thiết kế chi tiết
7. Giá trị cần xác nhận (trỏ tới mã `D-xx` trong `decisions.md`)
8. Kiểm thử và đo lường
9. Tiêu chí hoàn thành (Definition of Done)
10. Rủi ro

**Plan stage** gồm:
1. Mục tiêu
2. Input / Output
3. Thuật toán (kèm hàm nguồn trong repo tham chiếu nếu có)
4. Config keys
5. Giá trị cần xác nhận
6. File
7. Trường hợp biên
8. Test
9. Đo lường
10. Tiêu chí hoàn thành

## 4. Quy ước chung cho mọi milestone
- **Code trên thiết bị** (`src/edgeface/`, `scripts/`) phải tương thích Python 3.6 và kiểm tra bằng `vermin --target=3.6- --violations`.
- Không dùng các API numpy mới hơn bản 1.13 của Ubuntu 18.04: tránh `argsort(kind="stable")`, `np.random.default_rng` và các API tương tự.
- Mọi ngưỡng nằm trong `configs/default.yaml`. Giá trị chưa chốt để `null`, và code phải có nhánh xử lý an toàn khi gặp `null`.
- Mỗi stage trả về `StageResult(ok, reason, data)` và được bọc bởi `@timed("<stage>")`.
- Mỗi milestone kết thúc khi: test pass, plan được cập nhật trạng thái, và README gốc được cập nhật nếu cấu trúc thư mục thay đổi.
- Khi phạm vi thay đổi đáng kể so với plan đã duyệt: dừng lại, sửa plan trong thư mục này và xin duyệt lại.
