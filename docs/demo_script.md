# Kịch bản demo (M9-T06)

Khoảng 10 phút, chạy trên thiết bị thật. Mục tiêu: cho người xem thấy hệ thống **gợi ý**
chứ không tự quyết, và thấy nó từ chối ảnh giả.

## Chuẩn bị (làm trước, không nằm trong 10 phút)
```bash
ssh nano 'sudo jetson_clocks'                     # C-19, sau mỗi lần khởi động
scripts/dev_link.sh up                            # server + đường hầm + sync
ssh nano 'cd ~/edge-ai && python3 scripts/db_admin.py create-operator --name "Điều dưỡng A"'
ssh nano 'systemctl --user start edgeface-engine edgeface-kiosk'   # hoặc chạy tay
```
In sẵn một ảnh chân dung của chính người tham gia demo (để thử tấn công), và mở
`http://127.0.0.1:8000/admin/` trên máy chiếu.

## Phần 1 — Đăng ký bệnh nhân (2 phút)
1. Nhấn giữ góc dưới trái màn hình 3 giây → nhập PIN.
2. Tab **Đăng ký BN**: nhập mã, họ tên, năm sinh, mã lịch.
3. Nhấn **Bắt đầu chụp**, đứng vào khung. Màn hình đếm `1/5 … 5/5`.
4. Màn xem lại hiện cảnh báo nếu khuôn mặt giống bệnh nhân đã có. Nhấn **Lưu**.
5. Chỉ cho người xem: trang `/admin/patients` trên server đã có bệnh nhân này.

**Điểm cần nói:** ảnh khuôn mặt không được lưu, chỉ lưu vector đặc trưng; dữ liệu tự xoá
sau 24 giờ.

## Phần 2 — Nhận dạng (2 phút)
1. Lùi ra xa → màn hình báo *"Vui lòng đứng gần hơn"*.
2. Quay mặt sang bên → *"Vui lòng nhìn thẳng vào camera"*.
3. Đứng đúng tư thế → thẻ ứng viên hiện mã, tên, năm sinh, mã lịch.
4. **Điều dưỡng bấm Xác nhận.** Chỉ ra đồng hồ đếm ngược: không ai bấm thì phiên tự huỷ.

**Điểm cần nói:** màn hình ghi "Khớp cao" hoặc "Cần kiểm tra", không hiện điểm số — con
số mời người ta tranh luận với mô hình, trong khi thang điểm chỉ có nghĩa sau hiệu chuẩn.

## Phần 3 — Chống giả mạo (2 phút)
1. Giơ ảnh in trước camera.
2. Màn hình chuyển đỏ: *"Nghi ngờ giả mạo khuôn mặt"*, **không hiện tên bệnh nhân nào**.
3. Mở `/admin/spoof` trên server: sự kiện đã tới nơi, kèm mã băm ảnh bằng chứng.

**Điểm cần nói:** ảnh bằng chứng nằm trên thiết bị và tự xoá sau 7 ngày; server chỉ giữ
mã băm để đối chiếu.

## Phần 4 — Thu hồi và offline (2 phút)
1. Trên server, nhấn **Thu hồi** bệnh nhân vừa đăng ký.
2. Đợi một chu kỳ sync (hoặc chạy `scripts/dev_link.sh check`).
3. Đứng lại trước kiosk → không còn nhận ra người đó nữa.
4. **Rút mạng khỏi server.** Đứng vào kiosk: vẫn nhận dạng bình thường. Cắm lại: các sự
   kiện dồn trong hàng đợi được đẩy lên hết, không trùng lặp.

## Phần 5 — Số liệu (2 phút)
```bash
ssh nano 'cd ~/edge-ai && python3 tools/eval/perf_report.py --db /home/js/var/edge.db'
ssh nano 'cd ~/edge-ai && python3 tools/eval/ops_report.py --db /home/js/var/edge.db'
```
Chiếu bảng latency từng stage và bảng chỉ số vận hành, cùng biểu đồ ROC/DET trong
`docs/figures/eval/`.

## Câu hỏi hay gặp
| Câu hỏi | Trả lời ngắn |
|---|---|
| Hệ thống có tự cho bệnh nhân vào không? | Không. Mọi kết quả đều cần điều dưỡng bấm xác nhận. |
| Có lưu ảnh mặt không? | Không, trừ ảnh bằng chứng khi nghi giả mạo (tự xoá sau 7 ngày). |
| Mất mạng thì sao? | Kiosk chạy bình thường; sự kiện dồn lại và gửi sau. |
| Nhận nhầm người thì sao? | Điều dưỡng bấm **Không phải** hoặc **Tìm thủ công**; mọi lượt đều được ghi log. |
