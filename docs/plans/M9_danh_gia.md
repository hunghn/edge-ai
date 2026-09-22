# M9 — Hiệu chuẩn ngưỡng, đánh giá, ablation và báo cáo

**Trạng thái:** ✅ Công cụ hoàn thành 2026-09-22 · số liệu chờ dataset (D-28) · **Cần Nano:** Có

> **Kết quả:** [`docs/results/M9_evaluation_tools.md`](../results/M9_evaluation_tools.md).
> 8 công cụ + 22 test trên dữ liệu có đáp án biết trước. Chạy thử trọn chuỗi trên clip tổng hợp: gallery → 72 dòng so sánh → metric → ROC/DET → ablation.
> `calibrate.py` **từ chối** chạy trên tập test và chỉ ghi đề xuất, không tự sửa config.
> Kịch bản demo: [`docs/demo_script.md`](../demo_script.md).

## 1. Mục tiêu và đầu ra
- **Bộ ngưỡng có luận cứ** cho các mục đang `null` (D-01, D-02, D-04 `no_match_below`, và D-05/D-08/D-15 nếu đưa vào hiệu chuẩn), được **người dùng duyệt** trước khi ghi vào `configs/default.yaml`.
- Bảng kết quả đầy đủ theo spec §5: nhận dạng, chống giả mạo, hiệu năng, vận hành. So sánh với baseline Haar+LBPH.
- Ma trận kịch bản + ablation.
- Bản nháp báo cáo, sau đó báo cáo hoàn chỉnh + demo (spec tuần 7).

## 2. Phạm vi
- **Làm:** công cụ tính metric/vẽ đồ thị, đề xuất ngưỡng, chạy ma trận kịch bản trên Nano, ablation, báo cáo.
- **Không làm:** huấn luyện lại model.

## 3. Nguyên tắc đánh giá
- **Tách dev/test theo người** (M8-T11). Ngưỡng **chỉ** chọn trên dev; mọi số báo cáo lấy trên test với ngưỡng cố định.
- Mọi chỉ số kèm **khoảng tin cậy**: bootstrap theo người, 1000 lần.
- Ghi phiên bản: sha256 model, commit git, config, chế độ nguồn Nano.
- Mọi kết quả sinh bằng script từ `scores` và `metrics` (tái lập được), không chỉnh tay.

## 4. Chỉ số

### 4.1 Nhận dạng (`tools/eval/recognition.py`)
| Chỉ số | Định nghĩa triển khai |
|---|---|
| TAR@FAR=1e-3, 1e-4 | Từ điểm genuine/impostor cấp **phiên** (sau S8 + S9); nội suy ngưỡng tại FAR mục tiêu. Nêu số phép impostor và giới hạn thống kê (xem M8 §4.2) |
| FRR | Tỉ lệ phiên genuine bị từ chối tại ngưỡng đã chọn (gồm cả `low_quality` → báo riêng hai phần) |
| Rank-1 | Tỉ lệ phiên genuine có top1 đúng người (open-set: chỉ tính khi người có trong gallery) |
| ROC, DET | Đồ thị matplotlib, trục DET theo thang normal deviate; so sánh pipeline chính với LBPH |
| Theo điều kiện | Tách theo ánh sáng / khoảng cách / tư thế / kính |

### 4.2 Chống giả mạo (`tools/eval/antispoof.py`, theo tinh thần ISO/IEC 30107-3)
| Chỉ số | Định nghĩa |
|---|---|
| APCER (theo từng PAI) | Tỉ lệ mẫu tấn công loại PAI bị chấp nhận là thật |
| APCER tổng | **Max** theo PAI (theo ISO), báo kèm trung bình |
| BPCER | Tỉ lệ mẫu thật bị từ chối là giả |
| ACER | (APCER_max + BPCER) / 2. Ghi chú: ISO/IEC 30107-3 bản mới không khuyến nghị ACER; báo cáo kèm vì spec yêu cầu |
| Đường cong | APCER theo BPCER (DET cho PAD); BPCER tại APCER = 5% / 10% |
| Mức | Cấp frame (gate S4) và cấp phiên (luật D-30) |

### 4.3 Hiệu năng (`tools/eval/perf_report.py`)
- Latency từng stage S0–S10 (mean/p50/p95), e2e p50/p95 và "thời gian đến khi hiện thẻ ứng viên".
- FPS, RAM đỉnh từng tiến trình (engine/kiosk/sync) và toàn hệ thống.
- CPU theo từng core, GPU% (GR3D), công suất (POM_5V_IN/GPU/CPU), nhiệt độ.
- Chế độ 10 W và 5 W; so sánh với baseline LBPH.

### 4.4 Vận hành (`tools/eval/ops_report.py`)
Tỉ lệ `review_required`, tỉ lệ `low_quality`, số lượt thử trung bình để định danh thành công (từ `sessions`/`sessions_log`: chuỗi `retry` đến `confirm`), tỉ lệ điều dưỡng phải tìm thủ công, phân bố `rule_id`.

## 5. Hiệu chuẩn ngưỡng (`tools/eval/calibrate.py`)
| Ngưỡng | Cách đề xuất trên tập dev | Ghi chú |
|---|---|---|
| `match.threshold` (D-01) | Điểm tại FAR = 1e-3 (hoặc mục tiêu FAR người dùng chọn) | Trình kèm TAR tương ứng và khoảng tin cậy |
| `match.margin_top1_top2` (D-02) | Quét lưới; chọn giá trị giảm nhận nhầm top1 mà không tăng FRR quá X điểm % | X do người dùng quyết |
| `decision.no_match_below` (D-04) | Điểm tại FAR = 1e-2 (vùng "chắc chắn không có trong danh sách") | |
| `antispoof.p_real_min` (D-05) | Giữ 0.85 theo spec; báo APCER/BPCER tại 0.85 và đề xuất điểm thay thế nếu BPCER quá cao | Chỉ đổi khi người dùng đồng ý |
| `pose_coarse.k_yaw` (D-15) | Hồi quy theo solvePnP (xem S3) | |
| `best_frame.quality_score` (D-08) | Chọn phương án A/B/C cho TAR@FAR cao nhất trên dev | Qua ablation |

Đầu ra: `docs/results/M9_threshold_proposal.md` (bảng đề xuất + đồ thị + lý do), chờ người dùng duyệt, sau đó cập nhật `decisions.md` và `configs/default.yaml`.

## 6. Ma trận kịch bản và ablation
| Mã | Thí nghiệm | Biến thay đổi | Chỉ số |
|---|---|---|---|
| E1 | Pipeline chính vs Haar+LBPH | Toàn bộ | ROC/DET, TAR@FAR, latency, RAM, công suất |
| E2 | Theo điều kiện thu | Ánh sáng, khoảng cách, tư thế, kính | TAR@FAR, `low_quality` rate |
| E3 | Anti-spoof theo PAI | 4 PAI × khoảng cách/góc | APCER/BPCER/ACER |
| A1 | Chỉ V2 / chỉ V1SE / cả hai | Fusion S4 | APCER/BPCER, latency S4 |
| A2 | Có / không gate S3 và S5 | Tắt gate | TAR@FAR, `low_quality`, thời gian đến quyết định |
| A3 | K = 1 / 3 / 5 frame; có / không vote | S8, S9 | TAR@FAR, thời gian |
| A4 | `quality_score` A / B / C / FIFO | S8 | TAR@FAR |
| A5 | 5 điểm từ SCRFD vs từ 106 điểm | S6 (D-09) | TAR@FAR |
| A6 | Gộp template `max` vs `mean` | S9 (D-03) | TAR@FAR, Rank-1 |
| A7 | FP16 (Nano) vs FP32 (ONNX, x86) | Độ chính xác số | Chênh TAR@FAR |
| A8 (tuỳ chọn) | w600k_mbf vs w600k_r50 (chỉ x86) | Model nhận dạng | TAR@FAR, để thấy cái giá của việc chọn model nhẹ cho Nano |

Mọi thí nghiệm chạy bằng `tools/eval/run_matrix.py --config experiments/<mã>.yaml`, kết quả ghi `results/<mã>/` (không commit dữ liệu thô, chỉ commit bảng tổng hợp và hình).

## 7. Công việc
| Mã | Công việc |
|---|---|
| M9-T01 | `tools/eval/{recognition,antispoof,perf_report,ops_report,calibrate,bootstrap}.py` + test đơn vị với dữ liệu tổng hợp có đáp án biết trước |
| M9-T02 | `tools/eval/run_matrix.py` + `experiments/*.yaml` |
| M9-T03 | Chạy trích điểm trên tập dev (Nano) → đề xuất ngưỡng → **người dùng duyệt** |
| M9-T04 | Chạy E1–E3, A1–A8 trên tập test với ngưỡng đã chốt |
| M9-T05 | `docs/results/M9_report_tables.md` + `docs/figures/` (ROC, DET, PAD, latency, RAM, công suất) |
| M9-T06 | Kịch bản demo (`docs/demo_script.md`): enroll → nhận dạng → xác nhận → thu hồi trên web → tấn công ảnh in |
| M9-T07 | Bản nháp báo cáo, sau đó bản hoàn chỉnh |

## 8. Giá trị cần xác nhận
- **D-18:** FAR mục tiêu để chọn `match.threshold` (1e-3 hay 1e-4).
- **D-18:** mức tăng FRR tối đa chấp nhận khi thêm margin (§5).
- Duyệt `M9_threshold_proposal.md` trước khi dùng ngưỡng cho tập test.

## 9. Kiểm thử công cụ
- `recognition.py`: phân bố genuine/impostor Gauss đã biết → TAR@FAR khớp giải tích (sai số < 1%).
- `antispoof.py`: ca nhỏ tính tay APCER/BPCER/ACER.
- `bootstrap.py`: seed cố định cho kết quả lặp lại được.

## 10. Tiêu chí hoàn thành
- [ ] Ngưỡng đã được người dùng duyệt và ghi vào `decisions.md` + config
- [ ] Đủ bảng/đồ thị cho 4 nhóm chỉ số spec §5, kèm khoảng tin cậy
- [ ] Ablation A1–A7 (A8 tuỳ chọn)
- [ ] Demo chạy trọn kịch bản
- [ ] Báo cáo hoàn chỉnh

## 11. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Không đủ dữ liệu để đo FAR = 1e-4 đáng tin | Báo TAR@FAR=1e-3 làm chỉ số chính, nêu rõ giới hạn |
| Hết thời gian cho ablation | Ưu tiên E1–E3, A1–A3; các mục còn lại là tuỳ chọn |
| Rò rỉ dữ liệu test vào hiệu chuẩn | `split.py` + kiểm tra tự động trong `calibrate.py` (từ chối nếu có ID test) |
