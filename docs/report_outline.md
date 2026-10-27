# Sườn báo cáo đồ án

## Đề tài

**Hệ thống nhận dạng khuôn mặt kết hợp chống giả mạo trên thiết bị Jetson Nano phục vụ xác minh bệnh nhân tại kiosk phòng khám IVF**

---

## Mục lục đề xuất

1. [Chương 1. Tổng quan đề tài](#chương-1-tổng-quan-đề-tài)
2. [Chương 2. Cơ sở lý thuyết](#chương-2-cơ-sở-lý-thuyết)
3. [Chương 3. Phân tích và thiết kế hệ thống](#chương-3-phân-tích-và-thiết-kế-hệ-thống)
4. [Chương 4. Triển khai hệ thống trên Jetson Nano](#chương-4-triển-khai-hệ-thống-trên-jetson-nano)
5. [Chương 5. Thực nghiệm và đánh giá](#chương-5-thực-nghiệm-và-đánh-giá)
6. [Chương 6. Kết luận và hướng phát triển](#chương-6-kết-luận-và-hướng-phát-triển)

---

# Chương 1. Tổng quan đề tài

## 1.1. Bối cảnh và lý do chọn đề tài

- Nhu cầu xác minh danh tính bệnh nhân tại các cơ sở y tế và phòng khám IVF.
- Hạn chế của phương pháp xác minh thủ công:
  - phụ thuộc vào giấy tờ và thao tác của nhân viên;
  - có thể xảy ra nhầm lẫn khi tiếp nhận nhiều bệnh nhân;
  - khó truy vết đầy đủ quá trình xác minh.
- Tiềm năng của nhận dạng khuôn mặt tại kiosk:
  - thao tác nhanh;
  - không tiếp xúc;
  - có thể hỗ trợ nhân viên y tế trong bước xác minh.
- Rủi ro khi chỉ sử dụng nhận dạng khuôn mặt:
  - ảnh chụp;
  - video phát lại;
  - màn hình điện thoại;
  - các hình thức giả mạo khác.
- Sự cần thiết của cơ chế chống giả mạo và xác nhận cuối cùng bởi nhân viên y tế.

## 1.2. Phát biểu bài toán

Xây dựng một hệ thống chạy tại biên trên Jetson Nano 4GB, sử dụng một camera RGB để:

1. phát hiện khuôn mặt;
2. kiểm tra chất lượng và tư thế khuôn mặt;
3. phát hiện dấu hiệu giả mạo;
4. tạo vector đặc trưng khuôn mặt;
5. tìm kiếm trong gallery bệnh nhân cục bộ;
6. hiển thị đề xuất danh tính cho nhân viên;
7. luôn yêu cầu nurse xác nhận trước khi hoàn tất phiên xác minh.

Hệ thống không tự động quyết định tiếp nhận bệnh nhân và không thay thế quyết định của nhân viên y tế.

## 1.3. Mục tiêu

### 1.3.1. Mục tiêu tổng quát

Thiết kế và triển khai hệ thống xác minh khuôn mặt có chống giả mạo, hoạt động offline-first trên Jetson Nano với tài nguyên hạn chế.

### 1.3.2. Mục tiêu cụ thể

- Triển khai pipeline xử lý khuôn mặt từ S0 đến S10.
- Sử dụng SCRFD `det_500m` cho phát hiện khuôn mặt.
- Sử dụng ArcFace `w600k_mbf` để tạo embedding.
- Sử dụng MiniFASNetV2 và MiniFASNetV1SE cho anti-spoofing.
- Sử dụng TensorRT FP16 để suy luận trên Jetson Nano.
- Xây dựng gallery cục bộ và tìm kiếm cosine bằng NumPy.
- Xây dựng kiosk UI tách biệt với engine.
- Giao tiếp giữa các process thông qua SQLite ở chế độ WAL.
- Xây dựng tiến trình đồng bộ dữ liệu với server.
- So sánh với baseline Haar Cascade kết hợp LBPH.
- Đo độ chính xác, độ trễ, FPS, RAM, CPU và công suất.

## 1.4. Đối tượng và phạm vi nghiên cứu

### 1.4.1. Đối tượng nghiên cứu

- Nhận dạng khuôn mặt trong điều kiện kiosk.
- Chống giả mạo khuôn mặt bằng camera RGB.
- Tối ưu suy luận mô hình trên thiết bị Jetson Nano.
- Thiết kế hệ thống edge/offline-first.

### 1.4.2. Phạm vi

- Thiết bị mục tiêu: Jetson Nano 4GB, JetPack 4.6.x.
- Camera: một camera RGB.
- Không sử dụng camera chiều sâu hoặc camera hồng ngoại.
- Quy mô dự kiến: khoảng 30–60 bệnh nhân đăng ký mỗi ngày.
- Không xét trường hợp đeo khẩu trang trong phạm vi chính của đề tài.
- Nhân viên y tế luôn thực hiện bước xác nhận cuối cùng.

### 1.4.3. Ngoài phạm vi

- Không tự động cấp quyền tiếp nhận bệnh nhân.
- Không thay thế hệ thống hồ sơ bệnh án.
- Không sử dụng PyTorch, ONNX Runtime, Milvus hoặc Flask trên Jetson Nano.
- Không xây dựng hệ thống nhận dạng đa camera.

## 1.5. Những thách thức

- Tài nguyên CPU, GPU và RAM hạn chế.
- TensorRT engine phụ thuộc phiên bản phần cứng và phần mềm.
- OpenCV trên thiết bị không được giả định có CUDA.
- Điều kiện ánh sáng, khoảng cách và góc mặt thay đổi.
- Cần giảm tỷ lệ giả chấp nhận nhưng vẫn giữ trải nghiệm sử dụng.
- Cần hoạt động khi mất kết nối mạng.
- Dữ liệu khuôn mặt và evidence là dữ liệu nhạy cảm.

## 1.6. Đóng góp của đề tài

- Đề xuất pipeline nhận dạng kết hợp anti-spoofing phù hợp Jetson Nano.
- Thiết kế kiến trúc tách engine, kiosk và sync.
- Xây dựng cơ chế lưu trữ và IPC dựa trên SQLite WAL.
- Xây dựng phương pháp chọn best-frame dựa trên chất lượng ảnh.
- Xây dựng quy trình đánh giá so sánh với Haar + LBPH.
- Đo lường khả năng chạy thực tế trên nền tảng edge có tài nguyên hạn chế.

## 1.7. Tổ chức báo cáo

Báo cáo được tổ chức thành sáu chương:

- **Chương 1** trình bày bối cảnh, bài toán, mục tiêu, phạm vi và đóng góp.
- **Chương 2** trình bày các cơ sở lý thuyết và công nghệ được sử dụng.
- **Chương 3** trình bày phân tích yêu cầu, kiến trúc và thiết kế pipeline.
- **Chương 4** trình bày quá trình triển khai hệ thống trên Jetson Nano.
- **Chương 5** trình bày phương pháp thực nghiệm và kết quả đánh giá.
- **Chương 6** tổng kết kết quả, hạn chế và hướng phát triển.

---

# Chương 2. Cơ sở lý thuyết

## 2.1. Tổng quan bài toán nhận dạng khuôn mặt

- Phân biệt face detection, face alignment, face verification và face identification.
- Quy trình tổng quát:
  1. phát hiện khuôn mặt;
  2. căn chỉnh;
  3. trích xuất đặc trưng;
  4. so khớp với gallery;
  5. đưa ra đề xuất và xác nhận.
- Phân biệt xác minh một-một và nhận dạng một-nhiều.

## 2.2. Phát hiện khuôn mặt với SCRFD

- Kiến trúc và mục tiêu của SCRFD.
- Lý do chọn phiên bản `det_500m` cho Jetson Nano.
- Bounding box và năm điểm landmark đầu vào.
- Tiền xử lý:
  - resize;
  - chuẩn hóa `(x - 127.5) / 128`;
  - giải mã output;
  - threshold score;
  - NMS.
- Vai trò của ngưỡng phát hiện trong S1.

## 2.3. Ước lượng tư thế khuôn mặt

- Yaw, pitch và roll.
- Tư thế thô từ năm keypoint.
- Tư thế tinh và các tỷ lệ landmark.
- Lý do dùng gate tư thế trước khi thực hiện các stage tốn tài nguyên hơn.
- Giới hạn của ước lượng tư thế bằng camera RGB.

## 2.4. Landmark 106 điểm và đánh giá chất lượng ảnh

- Mục đích của landmark 106 điểm.
- Các chỉ số:
  - độ mở mắt;
  - độ mở miệng;
  - hướng nhìn;
  - độ nghiêng;
  - độ sáng;
  - độ mờ.
- Variance của Laplacian để đánh giá blur.
- Vai trò của IQA trong việc chọn frame có chất lượng tốt.

## 2.5. Căn chỉnh khuôn mặt

- Ý nghĩa của similarity transform.
- Năm điểm landmark dùng cho ArcFace.
- Template ArcFace.
- Kích thước ảnh đầu ra `112 x 112`.
- Ảnh hưởng của alignment đến chất lượng embedding.

## 2.6. Trích xuất embedding với ArcFace

- Ý tưởng học metric embedding.
- Vector đặc trưng 512 chiều.
- Tiền xử lý RGB:
  - chuyển đổi màu;
  - chuẩn hóa `(x - 127.5) / 127.5`;
  - L2 normalization.
- So sánh cosine similarity.
- Lý do chọn `w600k_mbf` cho Jetson Nano.

## 2.7. Chống giả mạo với MiniFASNet

- Khái niệm presentation attack.
- Các loại giả mạo trong phạm vi đề tài:
  - ảnh in;
  - ảnh trên màn hình;
  - video phát lại.
- MiniFASNetV2 và MiniFASNetV1SE.
- Crop scale 2.7 và 4.0.
- Input `80 x 80 BGR`.
- Kết hợp softmax của hai mô hình.
- Phân loại lớp:
  - index 1 là real;
  - index 0 và 2 là spoof.
- Các chỉ số APCER, BPCER và ACER.

## 2.8. TensorRT và suy luận FP16

- Vai trò của TensorRT trong suy luận edge.
- Quy trình ONNX → TensorRT engine.
- Lý do chỉ sử dụng FP16.
- Tính phụ thuộc của engine vào:
  - GPU;
  - phiên bản TensorRT;
  - CUDA;
  - driver;
  - TensorRT builder.
- Nguyên tắc build engine trên chính Jetson Nano.

## 2.9. SQLite WAL và kiến trúc offline-first

- Đặc điểm của SQLite.
- Chế độ WAL và concurrent access.
- Lý do không sử dụng message broker trên thiết bị.
- Outbox pattern cho đồng bộ khi có mạng.
- Retention của gallery và evidence cục bộ.

## 2.10. Baseline Haar Cascade và LBPH

- Haar Cascade cho phát hiện khuôn mặt.
- LBPH cho mô tả và so khớp khuôn mặt.
- Ưu điểm và hạn chế của baseline truyền thống.
- Vai trò của baseline trong đánh giá cải thiện của pipeline đề xuất.

## 2.11. Tiêu chí đánh giá

- Nhận dạng:
  - TAR@FAR = `1e-3`;
  - TAR@FAR = `1e-4`;
  - FRR;
  - Rank-1;
  - ROC/DET.
- Anti-spoof:
  - APCER;
  - BPCER;
  - ACER.
- Hệ thống:
  - FPS;
  - latency từng stage;
  - p50/p95 end-to-end;
  - peak RAM;
  - CPU theo core;
  - công suất;
  - nhiệt độ.

---

# Chương 3. Phân tích và thiết kế hệ thống

## 3.1. Yêu cầu chức năng

- Hiển thị trạng thái sẵn sàng của kiosk.
- Thu nhận khung hình từ camera.
- Phát hiện và chọn khuôn mặt chính.
- Hướng dẫn người dùng điều chỉnh vị trí.
- Kiểm tra anti-spoofing.
- Đánh giá chất lượng ảnh.
- Đề xuất danh tính từ gallery.
- Cho phép nurse xác nhận, từ chối hoặc yêu cầu xử lý thủ công.
- Hỗ trợ enrollment bệnh nhân.
- Lưu event và evidence theo chính sách.
- Đồng bộ dữ liệu với server khi có mạng.
- Hoạt động offline khi server không khả dụng.

## 3.2. Yêu cầu phi chức năng

- Tương thích Python 3.6 trên thiết bị.
- Không sử dụng framework nặng trên Jetson Nano.
- Suy luận TensorRT FP16.
- Không commit TensorRT engine vào repository.
- Có thể khởi động lại từng process độc lập.
- Dữ liệu cục bộ được giới hạn thời gian lưu trữ.
- Lỗi phải được ghi nhận rõ ràng, không silently fallback.
- Có khả năng đo lường latency, FPS, RAM và công suất.

## 3.3. Kiến trúc tổng thể

Mô tả các thành phần:

```text
Camera
  │
  ▼
Capture thread ──► Engine process ──► SQLite state / events / outbox
                         │                         │
                         ▼                         ▼
                    TensorRT engines          Sync process ──► Server
                         │
                         ▼
                    Kiosk process
```

Trình bày trách nhiệm của từng process:

### Engine

- Điều khiển pipeline S0–S10.
- Nạp TensorRT engine.
- Quản lý session state machine.
- Ghi state cho kiosk.
- Ghi event, metrics và evidence.

### Kiosk

- Hiển thị preview và hướng dẫn.
- Hiển thị kết quả đề xuất.
- Nhận thao tác của nurse.
- Gửi command cho engine qua SQLite.

### Sync

- Đẩy outbox lên server.
- Kéo gallery, model bundle và revocation list.
- Retry và backoff khi mất mạng.

## 3.4. Pipeline S0–S10

### S0 — Capture

- Camera RGB sử dụng GStreamer `nvarguscamerasrc`.
- Thu ở độ phân giải 1080p.
- Resize về `640 x 640 BGR`.
- Ring buffer chỉ giữ frame mới nhất.
- Mục tiêu 10–15 FPS.

### S1 — Detect

- SCRFD `det_500m`.
- Score tối thiểu theo cấu hình.
- Không có khuôn mặt thì chuyển về `IDLE`.

### S2 — Subject

- Chọn bounding box lớn nhất.
- Kiểm tra vị trí trong ROI.
- Kiểm tra kích thước khuôn mặt.
- Nếu không đạt, hiển thị hướng dẫn “step closer” hoặc điều chỉnh vị trí.

### S3 — Coarse pose

- Ước lượng yaw và roll từ năm keypoint.
- Nếu vượt giới hạn, hiển thị “look straight”.
- Không thực hiện các stage sau khi tư thế thô không đạt.

### S4 — Anti-spoof

- Chạy MiniFASNetV2 và MiniFASNetV1SE.
- Crop theo bbox với scale tương ứng.
- Chuẩn hóa đúng định dạng BGR raw 0–255.
- Kết hợp softmax.
- Nếu nghi ngờ spoof:
  - chuyển trạng thái `spoof_suspect`;
  - lưu evidence theo chính sách;
  - không tiếp tục match.

### S5 — Landmark và IQA

- Chạy 2d106det trên crop `192 x 192`.
- Kiểm tra tư thế tinh.
- Kiểm tra mắt, miệng, độ sáng và độ mờ.
- Chỉ chấp nhận frame đạt toàn bộ gate chất lượng.

### S6 — Align

- Ước lượng similarity transform.
- Căn chỉnh theo ArcFace 5-point template.
- Xuất ảnh `112 x 112 RGB`.

### S7 — Embed

- Chạy ArcFace.
- Xuất embedding 512 chiều.
- L2 normalize trước khi lưu hoặc so khớp.

### S8 — Best-frame

- Thu thập tối đa 5 embedding trong tối đa 1.5 giây.
- Xếp hạng theo quality score.
- Nếu có ít hơn 3 frame tốt, chuyển `low_quality`.

### S9 — Match

- Tính cosine similarity với gallery cục bộ.
- Lấy top-1 và top-2.
- Áp dụng quy tắc vote 3-of-5.
- Nếu chưa đạt ngưỡng, chuyển `review_required`.

### S10 — Decide

- Kết hợp kết quả anti-spoof, chất lượng và matching.
- Không tự động xác nhận bệnh nhân.
- Luôn hiển thị nút nurse confirm.
- Lưu quyết định và người thực hiện quyết định.

## 3.5. State machine của phiên

Mô tả các trạng thái chính:

```text
IDLE
  → GUIDING
  → COLLECTING
  → DECIDED
  → AWAIT_NURSE
  → COOLDOWN
  → IDLE
```

Trình bày:

- sự kiện làm phát sinh chuyển trạng thái;
- điều kiện timeout;
- xử lý camera error;
- xử lý spoof;
- xử lý low quality;
- xử lý no match;
- xử lý confirm/reject/manual.

## 3.6. Thiết kế dữ liệu và SQLite

- Schema patient.
- Schema patient face templates.
- Schema session.
- Schema event.
- Schema evidence.
- Schema outbox.
- Schema kiosk state.
- Schema kiosk command.
- Schema model registry.
- Schema operator và PIN.
- WAL mode, busy timeout và transaction ngắn.
- Chính sách retention và xóa dữ liệu.

## 3.7. Thiết kế gallery

- Gallery là bản sao cục bộ theo ngày.
- Mỗi bệnh nhân có thể có nhiều template.
- Template có metadata model revision.
- Tìm kiếm brute-force cosine bằng NumPy.
- Tự động xóa sau 24 giờ theo chính sách.
- Tôn trọng revocation list từ server.

## 3.8. Thiết kế model bundle

- Manifest mô tả model và revision.
- Kiểm tra SHA-256.
- Kiểm tra chữ ký bundle.
- Kiểm tra từng file trong bundle.
- Staging bundle trước khi active.
- Không thay model đang chạy giữa một session.
- Engine chỉ nhận model sau khi restart hoặc reload an toàn.

## 3.9. Thiết kế bảo mật và quyền riêng tư

- Bảo vệ operator PIN.
- Giới hạn quyền file database và model.
- Không ghi log raw face embedding hoặc thông tin nhạy cảm không cần thiết.
- Evidence chỉ lưu khi cần điều tra spoof hoặc lỗi.
- Retention tự động.
- Đồng bộ qua HTTPS.
- Xử lý revocation.
- Audit event cho thao tác nurse.

## 3.10. Các giá trị cần hiệu chuẩn

Không tự ý kết luận các giá trị chưa có dữ liệu. Cần xác định bằng thực nghiệm:

- threshold matching S9;
- margin top-1/top-2;
- quy tắc vote;
- ngưỡng decision S10;
- ngưỡng anti-spoof trên tập validation;
- ngưỡng quality nếu cần điều chỉnh.

---

# Chương 4. Triển khai hệ thống trên Jetson Nano

## 4.1. Môi trường phần cứng và phần mềm

- Jetson Nano 4GB.
- JetPack 4.6.x.
- Ubuntu 18.04.
- Python 3.6.
- TensorRT 8.2.
- CUDA và cuDNN theo JetPack.
- OpenCV từ JetPack.
- GStreamer 1.14.5.
- SQLite 3.22.0.

Trình bày rõ các giới hạn:

- không dùng PyTorch trên thiết bị;
- không dùng ONNX Runtime trên thiết bị;
- không dùng Milvus;
- không giả định OpenCV CUDA;
- chỉ sử dụng TensorRT cho inference.

## 4.2. Chuẩn bị môi trường

- Cài dependency từ [requirements/device.txt](../requirements/device.txt).
- Kiểm tra phiên bản Python.
- Kiểm tra TensorRT/PyCUDA.
- Kiểm tra OpenCV và GStreamer.
- Kiểm tra camera bằng pipeline GStreamer.
- Kiểm tra dung lượng RAM và swap nếu có.

## 4.3. Chuyển đổi và build model

- Chuẩn bị ONNX trên máy phát triển.
- Kiểm tra input/output model.
- Kiểm tra parity giữa reference và ONNX.
- Chép ONNX lên Jetson Nano.
- Build engine bằng `trtexec`.
- Sử dụng FP16.
- Không build INT8.
- Lưu engine theo model revision.
- Kiểm tra engine bằng TensorRT backend.

## 4.4. Triển khai capture

- Cấu hình `nvarguscamerasrc`.
- Resize và chuyển đổi định dạng.
- Xử lý lỗi camera.
- Cơ chế ring buffer.
- Đo FPS capture.
- Xử lý frame stale.

## 4.5. Triển khai engine

- Khởi tạo config.
- Nạp model registry.
- Khởi tạo TensorRT backend.
- Khởi tạo SQLite.
- Khởi tạo session state machine.
- Chạy vòng lặp pipeline đơn luồng.
- Publish state cho kiosk.
- Ghi event và metrics.

## 4.6. Triển khai kiosk

- Hiển thị trạng thái camera.
- Hiển thị hướng dẫn tư thế và vị trí.
- Hiển thị kết quả anti-spoof.
- Hiển thị ứng viên nhận dạng.
- Hiển thị nút nurse confirm/reject/manual.
- Hỗ trợ enrollment và quản trị.
- Xử lý kiosk restart độc lập.

## 4.7. Triển khai sync

- Upload event theo batch.
- Retry với exponential backoff.
- Pull gallery.
- Pull model bundle.
- Pull revocation list.
- Hoạt động an toàn khi server không khả dụng.
- Không làm block engine.

## 4.8. Quản lý bằng systemd

- `edgeface-engine.service`.
- `edgeface-kiosk.service`.
- `edgeface-sync.service`.
- Thứ tự khởi động.
- Restart policy.
- Log và journal.
- Quyền chạy process.
- Thư mục dữ liệu và quyền truy cập.

## 4.9. Tối ưu tài nguyên

- Giới hạn số frame trong buffer.
- Tái sử dụng vùng nhớ khi có thể.
- Không chạy song song các stage inference trên một GPU.
- Theo dõi peak RAM.
- Đo CPU theo core.
- Đo nhiệt độ và công suất.
- Đảm bảo tổng footprint phù hợp ngân sách thiết bị.

## 4.10. Xử lý lỗi

- Camera không mở được.
- TensorRT engine không load được.
- Model bundle sai checksum.
- Database bị khóa.
- Server mất kết nối.
- Gallery hết hạn.
- Kiosk không phản hồi.
- Thiếu quyền ghi evidence.

Mỗi lỗi cần có:

- log;
- state hiển thị;
- hành động phục hồi;
- giới hạn retry;
- đường dẫn điều tra.

---

# Chương 5. Thực nghiệm và đánh giá

## 5.1. Mục tiêu thực nghiệm

- Đánh giá độ chính xác nhận dạng.
- Đánh giá khả năng chống giả mạo.
- Đánh giá hiệu năng trên Jetson Nano.
- So sánh với Haar + LBPH.
- Đánh giá ảnh hưởng của từng stage.
- Kiểm tra khả năng hoạt động offline-first.

## 5.2. Thiết kế dữ liệu

Mô tả:

- số lượng người tham gia;
- số phiên mỗi người;
- điều kiện ánh sáng;
- khoảng cách đến camera;
- góc quay;
- biểu cảm;
- dữ liệu genuine;
- dữ liệu impostor;
- dữ liệu spoof;
- cách chia train/gallery, validation và test.

Không để cùng một video hoặc các frame gần như trùng nhau xuất hiện ở cả train và test.

## 5.3. Kịch bản thu thập dữ liệu

### Dữ liệu nhận dạng

- Khuôn mặt chính diện.
- Góc yaw và roll trong giới hạn cho phép.
- Nhiều mức sáng.
- Nhiều khoảng cách.
- Nhiều phiên thu khác nhau.

### Dữ liệu anti-spoof

- Ảnh in.
- Ảnh hiển thị trên điện thoại.
- Video phát lại.
- Khuôn mặt thật trong điều kiện tương ứng.

### Dữ liệu baseline

- Dùng cùng camera, ánh sáng và tập đối tượng.
- Dùng cùng quy tắc chia dữ liệu.
- Dùng cùng tiêu chí đánh giá.

## 5.4. Hiệu chuẩn threshold

Trình bày quy trình:

1. tạo tập validation độc lập;
2. tính score genuine và impostor;
3. vẽ ROC/DET;
4. chọn threshold theo FAR mục tiêu;
5. kiểm tra lại trên test set;
6. ghi nhận confidence interval nếu có;
7. cập nhật config và model revision.

Các ngưỡng S9/S10 chưa được xem là chính thức nếu chưa qua bước này.

## 5.5. Đánh giá nhận dạng

### Chỉ số

- TAR@FAR = `1e-3`.
- TAR@FAR = `1e-4`.
- FRR.
- Rank-1.
- Top-2 accuracy.
- Tỷ lệ `review_required`.
- Tỷ lệ nurse confirmation.

### Phân tích

- Theo điều kiện ánh sáng.
- Theo khoảng cách.
- Theo yaw/roll.
- Theo chất lượng ảnh.
- Theo số lượng template trong gallery.
- Theo phiên bản model.

## 5.6. Đánh giá anti-spoof

- APCER.
- BPCER.
- ACER.
- Confusion matrix theo loại spoof.
- Ảnh hưởng của từng MiniFASNet.
- So sánh fusion và từng model riêng.
- Phân tích false positive/false negative.

## 5.7. Đánh giá chất lượng ảnh và best-frame

- So sánh nhận dạng:
  - frame đầu tiên;
  - frame ngẫu nhiên;
  - best-frame.
- Đánh giá ảnh hưởng của:
  - blur;
  - luminance;
  - mắt mở;
  - miệng đóng;
  - pose.
- Đánh giá số frame và thời gian thu thập.

## 5.8. Đánh giá hiệu năng

Đo các thông số:

- latency S0–S10;
- latency từng stage;
- p50/p95 end-to-end;
- FPS;
- peak RAM;
- CPU từng core;
- GPU utilization;
- nhiệt độ;
- công suất;
- thời gian khởi động engine;
- thời gian load engine;
- thời gian đồng bộ gallery.

Kết quả cần phân biệt:

- đo trên máy phát triển;
- đo trên Jetson Nano;
- đo với backend ONNX Runtime;
- đo với backend TensorRT.

## 5.9. So sánh với Haar + LBPH

So sánh ít nhất các tiêu chí:

- Rank-1;
- FRR;
- thời gian xử lý;
- RAM;
- độ nhạy với ánh sáng;
- độ nhạy với góc mặt;
- khả năng chống ảnh giả mạo;
- độ phức tạp triển khai.

Nêu rõ Haar + LBPH là baseline nhận dạng, không phải baseline anti-spoof đầy đủ.

## 5.10. Ablation study

Có thể đánh giá các cấu hình:

- bỏ S3 coarse pose;
- bỏ S5 IQA;
- không dùng best-frame;
- chỉ dùng một model anti-spoof;
- thay đổi số lượng template;
- thay đổi cách vote;
- so sánh cosine top-1 với 3-of-5 vote.

Mỗi ablation cần báo cáo cả accuracy và latency.

## 5.11. Đánh giá offline-first và độ tin cậy

- Mất mạng khi engine đang chạy.
- Mất mạng khi upload outbox.
- Server phục hồi.
- Gallery cục bộ còn hạn.
- Gallery hết hạn.
- Model bundle lỗi checksum.
- Kiosk restart.
- Engine restart.
- Database lock hoặc process chết đột ngột.

## 5.12. Phân tích kết quả

- Kết quả đạt mục tiêu nào.
- Mục tiêu nào chưa đạt.
- Nguyên nhân false reject.
- Nguyên nhân false accept.
- Trade-off giữa accuracy và latency.
- Trade-off giữa anti-spoof và trải nghiệm người dùng.
- Các giới hạn do camera RGB và Jetson Nano.

## 5.13. Tính tái lập

Ghi rõ:

- phiên bản source;
- phiên bản model;
- cấu hình;
- commit hoặc release;
- thông tin phần cứng;
- cách chạy test;
- cách tạo kết quả;
- cách lưu log và artifact.

---

# Chương 6. Kết luận và hướng phát triển

## 6.1. Kết quả đạt được

- Đã xây dựng được kiến trúc engine/kiosk/sync.
- Đã triển khai pipeline S0–S10.
- Đã tích hợp detector, landmark, anti-spoof và recognizer.
- Đã xây dựng gallery cục bộ và matching.
- Đã xây dựng SQLite WAL cho lưu trữ và IPC.
- Đã xây dựng cơ chế offline-first.
- Đã xây dựng baseline Haar + LBPH.
- Đã xây dựng bộ kiểm thử và công cụ đánh giá.

Các kết luận trong phần này phải dựa trên kết quả đo thực tế, không chỉ dựa trên việc test phần mềm thành công.

## 6.2. Hạn chế

- Camera chỉ có RGB.
- Khả năng chống giả mạo phụ thuộc dữ liệu huấn luyện và điều kiện thực tế.
- Jetson Nano có giới hạn RAM và năng lực tính toán.
- TensorRT engine phụ thuộc thiết bị.
- Một số threshold phải hiệu chuẩn theo dữ liệu triển khai.
- Hệ thống vẫn cần nurse xác nhận.
- Nhận dạng trong điều kiện che mặt hoặc ánh sáng cực đoan chưa nằm trong phạm vi chính.

## 6.3. Hướng phát triển

- Bổ sung camera IR hoặc depth nếu yêu cầu an toàn tăng lên.
- Cải thiện anti-spoof cho các hình thức tấn công mới.
- Tối ưu model và memory reuse.
- Xem xét batch hoặc scheduling phù hợp hơn nếu có nhiều camera.
- Bổ sung dashboard giám sát thiết bị.
- Tự động phát hiện drift dữ liệu.
- Quản lý model và threshold theo version.
- Cải thiện cơ chế audit và bảo vệ dữ liệu.
- Mở rộng đánh giá trên nhiều cơ sở và nhiều điều kiện ánh sáng.
- Nghiên cứu thay thế Jetson Nano bằng nền tảng edge mới hơn nếu cần hiệu năng cao hơn.

## 6.4. Kết luận cuối cùng

Khẳng định hệ thống là công cụ hỗ trợ xác minh danh tính tại kiosk, không phải hệ thống tự động ra quyết định y tế hoặc tự động tiếp nhận bệnh nhân. Mọi kết luận về độ tin cậy cần được trình bày cùng điều kiện dữ liệu, threshold, phiên bản model và phần cứng đã sử dụng.

---

# Phụ lục đề xuất

## Phụ lục A. Cấu trúc source code

Mô tả các thư mục:

- `src/edgeface/common/`
- `src/edgeface/pipeline/`
- `src/edgeface/models/`
- `src/edgeface/runtime/`
- `src/edgeface/engine/`
- `src/edgeface/kiosk/`
- `src/edgeface/storage/`
- `src/edgeface/sync/`
- `src/edgeface/gallery/`
- `src/edgeface/metrics/`
- `server/`
- `baselines/`
- `tests/`
- `scripts/`

## Phụ lục B. Cấu hình pipeline

- Bảng toàn bộ key trong `configs/default.yaml`.
- Giá trị cấu hình trên máy phát triển.
- Giá trị cấu hình trên Jetson Nano.
- Các threshold đã hiệu chuẩn.

## Phụ lục C. Database schema

- Các bảng.
- Quan hệ.
- Index.
- Chính sách retention.
- Ví dụ event và outbox record.

## Phụ lục D. Hướng dẫn triển khai

- Cài đặt môi trường.
- Chuẩn bị model.
- Build TensorRT engine.
- Cấu hình camera.
- Khởi động systemd services.
- Kiểm tra trạng thái.
- Thu thập log.
- Khôi phục khi có lỗi.

## Phụ lục E. Kết quả kiểm thử

- Danh sách test.
- Kết quả test.
- Test chạy trên máy phát triển.
- Test chạy trên Jetson Nano.
- Các test bị bỏ qua và lý do.

## Phụ lục F. Bảng truy vết yêu cầu

| Mã yêu cầu | Mô tả | Module | Test | Kết quả |
|---|---|---|---|---|
| REQ-S1 | Phát hiện khuôn mặt theo score threshold | `pipeline/detect.py` | `test_stage_gates.py` | Cập nhật sau khi chạy Nano |
| REQ-S4 | Phát hiện khuôn mặt giả mạo | `pipeline/antispoof.py` | Anti-spoof tests | Cập nhật sau khi có dataset |
| REQ-S8 | Chọn best-frame trong giới hạn thời gian | `pipeline/best_frame.py` | `test_best_frame.py` | Đã kiểm thử logic |
| REQ-S9 | Matching với gallery cục bộ | `pipeline/matcher.py` | `test_matcher.py` | Cập nhật sau calibration |
| REQ-S10 | Luôn yêu cầu nurse xác nhận | `pipeline/decision.py` | `test_decision.py` | Đã kiểm thử logic |
| REQ-OFFLINE | Pipeline tiếp tục hoạt động khi mất mạng | `sync/`, `storage/` | Integration tests | Cập nhật sau kiểm thử thiết bị |

