# M7 — Kết quả server và tiến trình sync

**Ngày:** 2026-09-22 · **Server:** FastAPI + SQLite trên PC · **Sync:** Python 3.6 trên Nano

Hướng dẫn cài đặt: [`server/README.md`](../../server/README.md).

## 1. Đã làm
| Thành phần | Nội dung |
|---|---|
| API thiết bị | `POST /events` (idempotent), `GET /gallery`, `GET /revocations`, `GET /bundles/*`, `POST /devices/heartbeat` |
| Web quản trị | đăng nhập, tổng quan 24 h, bệnh nhân + thu hồi, import CSV lịch hẹn, lịch sử phiên + xuất CSV, sự kiện giả mạo, quản lý thiết bị |
| Sync trên Nano | `uploader` (backoff luỹ thừa), `puller` (gallery + thu hồi), `bundle` (xác minh 4 lớp), heartbeat |
| CLI | `create-admin`, `create-device`, `sign-bundle`, `import-appointments` |

## 2. Kiểm chứng
| Bộ test | Số lượng | Nơi chạy |
|---|---|---|
| `server/tests` | 26 | máy dev |
| `tests/unit/test_sync.py` | 16 | máy dev **và Nano** |
| `tests/integration` | 4 | máy dev, có **server uvicorn thật** |
| Toàn bộ | 294 pass, 2 skip | máy dev |
| Trên Nano | 253 pass | Python 3.6, `requests` 2.18.4 |

Bốn test tích hợp chạy đúng vòng nghiệp vụ thật:
1. Đăng ký BN ở kiosk → sync đẩy lên → thiết bị thứ hai kéo về thấy đủ 5 template, vector khớp từng phần tử.
2. Admin thu hồi trên server → lần pull kế tiếp xoá sạch BN đó khỏi thiết bị.
3. Server chết → outbox tích luỹ, không mất sự kiện nào, bật lại thì gửi hết.
4. Heartbeat cập nhật trang thiết bị.

## 3. Bốn quyết định thiết kế
1. **Trùng sự kiện = đã gửi.** Khi server trả `duplicate`, thiết bị đánh dấu đã gửi. Nếu giữ lại thì một lần timeout mạng sẽ khiến sự kiện kẹt trong hàng đợi vĩnh viễn.
2. **Sự kiện bị từ chối thì giữ lại, không xoá.** Ghi log rõ và lùi lịch thử lại; không bao giờ âm thầm vứt dữ liệu của phòng khám.
3. **Một sự kiện hỏng không chặn cả lô.** Server nhận phần còn lại và trả lỗi riêng cho sự kiện hỏng, nếu không một payload dị dạng sẽ chặn hàng đợi mãi mãi.
4. **Enroll tại kiosk không bị pull xoá mất.** Pull chỉ thay phần `source = 'server'`; BN enroll tại chỗ có thể chưa kịp lên server. Ngược lại, **thu hồi thì xoá bất kể nguồn nào**.

## 4. Xác minh gói model (4 lớp)
Một file model là logic thực thi trá hình: detector bị sửa có thể được làm cho "thấy mặt" ở chỗ không có ai. Nên trước khi staging, thiết bị kiểm tra:
1. SHA-256 của archive khớp con số server công bố;
2. chữ ký HMAC-SHA256 khớp khoá chung (D-24);
3. giải nén an toàn — từ chối đường dẫn tuyệt đối, `..` và symlink (chống ghi đè ra ngoài thư mục);
4. mọi file trong manifest có mặt và khớp sha256 của chính nó.

Gói chỉ được **staged**, không kích hoạt: engine nạp model lúc khởi động, nên việc đổi model xảy ra khi restart chứ không giữa phiên.

Có test cho cả bốn kiểu hỏng: sai sha256, sai chữ ký, thiếu manifest, và file bên trong bị tráo.

## 5. Bảo mật — đã làm và chưa làm
**Đã làm:** token thiết bị lưu dạng băm (rò DB không lấy được token dùng được); token chỉ hiện một lần; mật khẩu admin dùng PBKDF2-HMAC-SHA256 của thư viện chuẩn; CSRF token cho mọi form quản trị; cookie `SameSite=lax`.

**Chưa làm / cần bạn quyết:**
- **HTTPS bắt buộc:** hiện có hướng dẫn chứng chỉ tự ký + ghim CA, nhưng chưa có cơ chế ép HTTPS. Dữ liệu là embedding khuôn mặt nên **không được chạy HTTP trần với bệnh nhân thật**.
- **D-22:** thời gian giữ embedding và log trên server — chưa chốt, hiện giữ vô thời hạn.
- **Thử nghiệm giữa hai máy thật chưa chạy:** máy dev là WSL2 (NAT) nên Nano chưa kết nối tới được. Cần một PC trong LAN; các test tích hợp hiện chạy cả hai phía trên cùng một máy.

## 6. Còn lại
- Chạy thử Nano ↔ server trên LAN thật (cần PC/laptop).
- Chốt D-22 và D-29 (tài khoản quản trị).
- `passlib` đã bị loại khỏi phụ thuộc: bản `bcrypt` 4.x làm nó lỗi ngay khi khởi tạo; dùng PBKDF2 của thư viện chuẩn, cùng cách với PIN trên thiết bị.
