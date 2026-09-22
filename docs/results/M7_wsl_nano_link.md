# Kết nối Nano ↔ server chạy trên WSL2

WSL2 mặc định nằm sau NAT: nó ra Internet được, nhưng thiết bị khác trong LAN **không**
gọi ngược vào được. Dưới đây là ba cách, xếp theo thứ tự nên dùng.

## Cách 1 — Đường hầm ngược qua SSH (đã tự động hoá, không cần quyền admin)

Dùng chính kết nối SSH sẵn có. Server nghe ở `127.0.0.1` trong WSL, cổng 8000 trên Nano
được chuyển tiếp về đó.

### Dùng script (khuyến nghị)

```bash
scripts/dev_link.sh up        # cài + chạy tất cả, cả hai máy
scripts/dev_link.sh status    # xem gì đang chạy ở đâu
scripts/dev_link.sh check     # chạy một chu kỳ sync trên Nano rồi báo kết quả
scripts/dev_link.sh logs      # xem log server + đường hầm
scripts/dev_link.sh down      # dừng (không gỡ cài đặt)
```

`up` làm những việc sau, và chạy lại nhiều lần cũng không sao:

| Máy | Việc |
|---|---|
| WSL | tạo `~/.config/edgeface/server.env` (DB, khoá secret ngẫu nhiên) nếu chưa có |
| WSL | cài 2 systemd **user service**: `edgeface-server` (uvicorn) và `edgeface-tunnel` (ssh −R), cả hai `Restart=always` |
| WSL | tạo thiết bị trên server và lấy token — **chỉ khi Nano chưa có token** |
| Nano | ghi `~/.config/edgeface/sync.env` (quyền 600) và `~/sync_nano.yaml` |
| Nano | cài + chạy user service `edgeface-sync` |

Token không bao giờ được in ra màn hình hay ghi vào log: script chuyển thẳng sang Nano
và đặt quyền 600.

Biến môi trường để đổi mặc định: `EDGEFACE_NANO_HOST` (mặc định `nano`),
`EDGEFACE_PORT` (8000), `EDGEFACE_DEVICE_ID` (kiosk-01).

Tạo tài khoản quản trị (một lần):
```bash
set -a; . ~/.config/edgeface/server.env; set +a
.venv/bin/python -m server.cli create-admin --username admin
```
rồi mở `http://127.0.0.1:8000/admin/`.

**Dịch vụ dừng khi bạn đăng xuất**, trừ khi bật lingering (cần sudo, chạy một lần):
```bash
sudo loginctl enable-linger $USER                  # trên WSL
ssh nano 'sudo loginctl enable-linger $USER'       # trên Nano
```

### Làm bằng tay (nếu không dùng script)

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000
ssh -f -N -R 8000:127.0.0.1:8000 -o ExitOnForwardFailure=yes nano
# trên Nano: export EDGEFACE_SERVER=http://127.0.0.1:8000
```

**Đã chạy thật ngày 2026-09-22, đủ vòng nghiệp vụ:**

| Bước | Kết quả |
|---|---|
| Nano đẩy outbox | 2 sự kiện, `pending: 0` |
| Server nhận | 1 bệnh nhân, 5 template, 1 phiên `review_required / confirm` |
| Nano kéo gallery | 1 bệnh nhân, 5 template |
| Heartbeat | server thấy `gallery ver: 2`, `last_seen` cập nhật |
| Admin thu hồi trên server → Nano pull | `applied 1 revocation`, thiết bị còn **0 bệnh nhân, 0 template** |

**Đã kiểm chứng khả năng tự hồi phục:** giết tiến trình ssh của đường hầm → systemd dựng
lại sau 5 giây (PID đổi 12829 → 12874), `status` báo "tunnel OK" trở lại. Không cần
`autossh`; `Restart=always` của systemd làm đúng việc đó.

**Ưu:** không đụng vào Windows, không cần IP tĩnh, đi qua SSH nên đã mã hoá sẵn, và cổng
8000 chỉ mở trên `127.0.0.1` nên không lộ ra LAN.
**Nhược:** chỉ dùng để phát triển/demo — cần máy dev bật và phiên WSL đang chạy. Không
phải cách triển khai cho phòng khám.

## Cách 2 — Chế độ mạng mirrored (gọn nhất cho LAN thật)

Máy này đang chạy **WSL 2.6.1**, đủ mới để dùng. Ở chế độ này WSL dùng chung card mạng
với Windows, nên cứ bind `0.0.0.0` là thiết bị khác trong LAN gọi tới được.

Tạo `C:\Users\<tên>\.wslconfig`:
```ini
[wsl2]
networkingMode=mirrored
```
rồi trong PowerShell: `wsl --shutdown`, mở lại WSL và chạy
`uvicorn server.app:app --host 0.0.0.0 --port 8000`.
Trên Nano dùng `EDGEFACE_SERVER=http://<IP-LAN-của-Windows>:8000`.

Có thể phải mở tường lửa Windows cho cổng 8000 (PowerShell quyền admin):
```powershell
New-NetFirewallRule -DisplayName "edgeface server" -Direction Inbound `
  -LocalPort 8000 -Protocol TCP -Action Allow
```

**Lưu ý:** mirrored mode đổi cách toàn bộ mạng WSL hoạt động, nên thử khi không đang bận việc khác.

## Cách 3 — Chuyển tiếp cổng của Windows (netsh portproxy)

Khi không bật được mirrored mode. Trong PowerShell **quyền admin**:
```powershell
$wslIp = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 `
  connectport=8000 connectaddress=$wslIp
New-NetFirewallRule -DisplayName "edgeface server" -Direction Inbound `
  -LocalPort 8000 -Protocol TCP -Action Allow
```
**Nhược:** IP của WSL đổi sau mỗi lần khởi động lại, nên phải chạy lại lệnh trên (hoặc
đặt nó vào một script chạy lúc đăng nhập).

## Khuyến nghị
- **Phát triển và demo:** cách 1, không phiền tới Windows.
- **Thử nghiệm trong phòng khám:** đừng chạy server trên WSL. Cài thẳng lên một PC/laptop
  Linux hoặc Windows trong LAN, bật HTTPS và ghim CA theo `server/README.md`. WSL là môi
  trường phát triển, không phải nơi chạy dịch vụ cho bệnh nhân thật.
