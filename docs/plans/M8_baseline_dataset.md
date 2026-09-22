# M8 — Baseline Haar+LBPH và thu thập dataset

**Trạng thái:** ✅ Phần công cụ hoàn thành 2026-09-22 · thu dữ liệu chờ duyệt D-28 · **Cần Nano:** Có

> **Kết quả:** [`docs/results/M8_baseline.md`](../results/M8_baseline.md).
> D-27 chốt: tự viết LBPH bằng numpy (C-23), có 10 test đối chứng `cv2.face`.
> Đo trên Nano: baseline **221 ms/frame (4.4 FPS)** so với pipeline chính 89 ms (11.2 FPS) — chậm hơn 2.5 lần vì Haar chạy CPU còn OpenCV của JetPack không có CUDA.
> Giao thức thu thập và phiếu đồng ý đã soạn, **chờ duyệt D-28 trước khi quay**.

## 1. Mục tiêu và đầu ra
- **Baseline cổ điển** Haar cascade + LBPH chạy **trên cùng Nano, cùng nguồn camera, cùng bộ đo latency/RAM/công suất**. Đây là yêu cầu của spec.
- **Dataset** theo kịch bản môi trường mô phỏng khu tiền thủ thuật, đủ để tính:
  - TAR@FAR=1e-3/1e-4, FRR, Rank-1, ROC/DET
  - APCER/BPCER/ACER cho anti-spoof
  - chỉ số vận hành

  Kèm **phiếu đồng ý** và quy trình bảo vệ dữ liệu.

## 2. Phạm vi
- **Làm:** baseline, công cụ ghi/gán nhãn dữ liệu, giao thức thu thập, cấu trúc dataset, tách tập dev/test, thiết lập tấn công trình diện (PAI).
- **Không làm:** tính metric và báo cáo (M9); dữ liệu bệnh nhân thật (spec: môi trường **mô phỏng**, người tham gia tình nguyện).

## 3. Phần A — Baseline Haar + LBPH

### 3.1 Thiết kế
```
baselines/haar_lbph/
  detector.py   # cv2.CascadeClassifier(haarcascade_frontalface_default.xml), scaleFactor/minNeighbors trong config
  lbph.py       # nhận dạng LBPH (cv2.face hoặc bản numpy, theo D-27)
  enroll.py     # từ ảnh/video enroll → model LBPH (lưu .yml/.npz)
  run.py        # đọc cùng FrameSource (S0), cùng @timed, xuất frames.csv cùng định dạng M3
configs/baseline.yaml
```
- Tiền xử lý: ảnh xám, crop theo Haar, resize cố định, `equalizeHist`. Tham số ghi trong config và báo cáo.
- **Không có anti-spoof** trong baseline. So sánh anti-spoof là "không có" và "MiniFASNet"; điểm này ghi rõ trong báo cáo.
- **Điểm số:** LBPH trả khoảng cách (thấp = giống). Đổi dấu thành điểm tương đồng để dùng chung công cụ ROC/DET ở M9.

### 3.2 D-27: nguồn LBPH
1. Kiểm tra wheel `opencv-contrib-python` aarch64 cho cp36 (**không** cài song song với OpenCV của JetPack trong cùng môi trường; dùng venv riêng cho baseline).
2. Nếu không có: tự viết LBPH bằng numpy: LBP 8 lân cận bán kính 1, lưới 8×8, histogram 256 bin, khoảng cách chi-square. Viết thêm test so với `cv2.face` trên máy dev để chứng minh tương đương.
3. Build OpenCV contrib từ nguồn trên Nano chỉ là phương án cuối (tốn nhiều giờ, dễ làm hỏng OpenCV của JetPack).

### 3.3 Công việc A
| Mã | Công việc |
|---|---|
| M8-T01 | Kiểm tra wheel contrib và chốt D-27 |
| M8-T02 | `detector.py`, `lbph.py` (+ test so với `cv2.face` trên dev nếu tự viết) |
| M8-T03 | `enroll.py`, `run.py` dùng lại `pipeline/capture.py` và `common/timing.py` |
| M8-T04 | Chạy baseline trên Nano với cùng video offline như M3; ghi latency/FPS/RAM/công suất |
| M8-T05 | Xuất điểm số genuine/impostor trên dataset (§4) theo định dạng chung cho M9 |

## 4. Phần B — Dataset

### 4.1 Nguyên tắc
- Người tham gia là **tình nguyện viên** (sinh viên, nhân viên), ký **phiếu đồng ý** nêu rõ:
  - mục đích
  - loại dữ liệu (video khuôn mặt)
  - nơi lưu, thời hạn lưu và xoá
  - quyền rút lui
  - không công bố hình ảnh nhận diện được (trừ khi đồng ý riêng)
- Mẫu phiếu: `docs/dataset/phieu_dong_y.md` (cần người hướng dẫn/phòng khám duyệt).
- Dữ liệu thô **không** vào git. Lưu trên ổ mã hoá, ghi đường dẫn trong `data/README.md` (không commit dữ liệu). Mã hoá người tham gia bằng ID ngẫu nhiên (`P001`...), bảng ánh xạ tên–ID để riêng, hạn chế quyền truy cập.

### 4.2 Giao thức thu thập (đề xuất, D-28)
| Hạng mục | Đề xuất |
|---|---|
| Số người | 30–60 (khớp quy mô spec) |
| Số buổi | 2 buổi khác ngày cho mỗi người: buổi 1 dùng để enroll, buổi 2 để probe (tránh lạc quan do cùng điều kiện) |
| Kịch bản mỗi buổi | Ánh sáng: phòng bình thường / tối / ngược sáng. Khoảng cách: gần / chuẩn / xa ngưỡng. Tư thế: thẳng / quay trái-phải ~20° / cúi-ngửa. Phụ kiện: kính / không kính. Mỗi kịch bản quay 5–10 s theo đúng luồng kiosk |
| Tấn công trình diện (PAI) | (1) ảnh in A4 giấy thường, (2) ảnh in giấy ảnh bóng, (3) phát lại trên điện thoại, (4) phát lại trên tablet/laptop. Mỗi loại ở 2 khoảng cách, 2 góc; nguồn ảnh là ảnh chụp chính người tham gia (có đồng ý) |
| Thiết bị ghi | Chính camera kiosk trên Nano, cùng vị trí lắp đặt |
| Nhãn | `participant_id, session, scenario, is_attack, pai_type, lighting, distance, pose, glasses` trong `manifest.csv` |

**Ước lượng số phép so sánh** để kiểm tra khả năng đo FAR = 1e-4, với 60 người, mỗi người ~20 probe (các frame/đoạn khác nhau):
- impostor ≈ 60 × 20 × 59 ≈ 70 800 phép so sánh
- tại FAR = 1e-4 chỉ khoảng 7 lỗi kỳ vọng

Như vậy khoảng tin cậy rất rộng, và các probe của cùng người không độc lập. Báo cáo phải nêu giới hạn này; TAR@FAR=1e-3 là chỉ số chính đáng tin hơn. Con số cuối cùng tính lại sau khi chốt D-28.

### 4.3 Công cụ
| Mã | Công việc |
|---|---|
| M8-T10 | `tools/dataset/record.py`: chạy trên Nano, hiển thị kịch bản cần quay, ghi video + nhãn vào `manifest.csv`; kiểm tra tiêu chí ghi (độ dài, FPS) |
| M8-T11 | `tools/dataset/split.py`: tách **theo người** thành dev (hiệu chuẩn ngưỡng) / test (báo cáo), cố định seed, lưu danh sách ID |
| M8-T12 | `tools/dataset/build_gallery.py`: enroll từ buổi 1 bằng pipeline thật → gallery DB dùng cho đánh giá |
| M8-T13 | `tools/dataset/extract_scores.py`: chạy pipeline (hoặc baseline) trên probe → `scores.parquet/csv`: `probe_id, participant_id, claimed_id, score, is_genuine, p_real, is_attack, pai_type, decision, rule_id, latency` |
| M8-T14 | `docs/dataset/protocol.md`: giao thức chi tiết + checklist mỗi buổi quay |
| M8-T15 | `docs/dataset/phieu_dong_y.md` |

## 5. Giá trị cần xác nhận
- **D-27:** nguồn LBPH.
- **D-28:** số người, số buổi, danh sách kịch bản và PAI, tỉ lệ dev/test.
- **Phiếu đồng ý và nơi lưu trữ dữ liệu:** cần người hướng dẫn/đơn vị duyệt.

## 6. Kiểm thử
- Baseline: test đơn vị cho LBPH numpy (nếu tự viết); `run.py` xuất đúng định dạng `frames.csv`.
- Dataset: `split.py` đảm bảo không người nào xuất hiện ở cả dev và test (test tự động); `manifest.csv` được kiểm tra schema.

## 7. Tiêu chí hoàn thành
- [ ] Baseline chạy trên Nano, có số liệu hiệu năng cùng định dạng M3
- [ ] Dataset đủ theo D-28, có phiếu đồng ý lưu trữ đúng quy trình
- [ ] `scores` cho pipeline chính và baseline trên tập dev/test sẵn sàng cho M9

## 8. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Thiếu người tham gia | Bắt đầu tuyển từ tuần 2; giảm kịch bản thay vì giảm số người |
| Cài opencv-contrib phá OpenCV của JetPack | venv riêng hoặc bản numpy |
| Dữ liệu tấn công không đa dạng | Tối thiểu 4 PAI; ghi rõ giới hạn |
