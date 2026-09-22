# Giao thức thu thập dữ liệu (đề xuất — D-28 chưa chốt)

> **Đây là bản đề xuất.** Số người, số buổi và danh sách kịch bản cần bạn và người hướng
> dẫn duyệt trước khi quay buổi đầu tiên. Quay xong mới đổi giao thức thì dữ liệu cũ hỏng.

## 1. Nguyên tắc
- Người tham gia là **tình nguyện viên**, không phải bệnh nhân thật. Spec ghi rõ môi
  trường là "mô phỏng khu tiền thủ thuật".
- Mỗi người ký **phiếu đồng ý** ([`phieu_dong_y.md`](phieu_dong_y.md)) trước khi quay.
- Người tham gia chỉ được nhận diện bằng **mã** (`P001`, `P002`...). Bảng ánh xạ mã ↔ tên
  giữ trên giấy cùng phiếu đồng ý, **không** vào repo, không vào manifest.
- Dữ liệu thô không bao giờ vào git. Lưu trên ổ mã hoá; `data/` đã nằm trong `.gitignore`.

## 2. Quy mô đề xuất
| Hạng mục | Đề xuất | Lý do |
|---|---|---|
| Số người | 30–60 | khớp quy mô một ngày của trung tâm IVF trong spec |
| Số buổi mỗi người | 2, **khác ngày** | buổi 1 để đăng ký, buổi 2 để nhận dạng. Dùng chung một buổi sẽ cho kết quả lạc quan giả vì cùng ánh sáng, cùng quần áo, cùng kiểu tóc |
| Độ dài mỗi clip | 6 giây | đủ cho vài lượt thu thập 1.5 giây |
| Thiết bị | chính camera kiosk, đúng vị trí lắp | khác camera thì số đo không dùng được |

## 3. Ma trận kịch bản (mỗi người, mỗi buổi)
| Kịch bản | Điều kiện | Mục đích |
|---|---|---|
| `normal` | ánh sáng phòng, đứng thẳng, khoảng cách chuẩn | điều kiện cơ bản |
| `dark` | giảm đèn | gate độ sáng (S5) |
| `backlit` | ngược sáng cửa sổ | trường hợp khó nhất trong thực tế |
| `near` | gần hơn một bước | |
| `far` | xa tới giới hạn | hiệu chuẩn `min_side_px` (D-07) |
| `turn` | quay trái/phải ~20° | gate yaw (S3, S5) |
| `nod` | cúi/ngửa nhẹ | gate pitch |
| `glasses` | đeo kính (nếu có) | ảnh hưởng của kính |

## 4. Tấn công trình diện (PAI)
Chỉ dùng ảnh của **chính người tham gia**, và chỉ khi họ đồng ý riêng mục này.

| Mã | Vật liệu | Ghi chú |
|---|---|---|
| `print_matte` | ảnh in giấy thường A4 | rẻ nhất, hay gặp nhất |
| `print_glossy` | ảnh in giấy ảnh bóng | phản xạ khác hẳn giấy thường |
| `replay_phone` | phát lại trên điện thoại | |
| `replay_tablet` | phát lại trên tablet/laptop | màn lớn, ít viền hơn |

Mỗi loại quay ở 2 khoảng cách và 2 góc nghiêng.

## 5. Quy trình một buổi
1. Kiểm tra phiếu đồng ý đã ký, cấp mã nếu người mới.
2. Chạy `sudo jetson_clocks` (C-19) nếu buổi đó có đo hiệu năng.
3. `python3 tools/dataset/record.py --participant P001 --session 1`
4. Với buổi có tấn công: thêm `--attacks`.
5. Sao lưu `data/raw/` sang ổ mã hoá ngay trong ngày.

## 6. Nhãn
`record.py` tự ghi `manifest.csv` với các cột: `clip, participant_id, session, scenario,
lighting, distance, pose, glasses, is_attack, pai_type, frames, recorded_at`.

## 7. Chia dev/test
```bash
python tools/dataset/split.py --manifest data/raw/manifest.csv --out data/split.json
```
Chia **theo người**, không theo clip, seed cố định. Ngưỡng chỉ được hiệu chuẩn trên tập
dev; mọi con số trong báo cáo lấy từ tập test.

## 8. Giới hạn thống kê cần nói rõ trong báo cáo
Với 60 người và ~20 probe mỗi người, số phép so sánh khác người khoảng
60 × 20 × 59 ≈ **70 800**. Ở FAR = 1e-4 chỉ kỳ vọng khoảng **7 lỗi**, nên khoảng tin cậy
rất rộng; các probe của cùng một người lại không độc lập với nhau. Vì vậy **TAR@FAR=1e-3
là chỉ số chính**, còn 1e-4 phải kèm khoảng tin cậy bootstrap và một câu nói rõ giới hạn
này. Con số cuối cùng tính lại sau khi chốt D-28.
