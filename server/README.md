# edgeface server

Máy chủ tối giản cho kiosk: nhận sự kiện, cấp gallery theo ngày, danh sách thu hồi và
gói model đã ký. Chạy trên PC/laptop trong LAN phòng khám, **không** chạy trên Nano.

## Cài đặt
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r server/requirements.txt

export EDGEFACE_DB="sqlite:///$PWD/server/server.db"   # hoặc postgresql://...
export EDGEFACE_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"

python -m server.cli create-admin --username admin
python -m server.cli create-device --id kiosk-01 --name "Kiosk tiền thủ thuật"
uvicorn server.app:app --host 0.0.0.0 --port 8000
```
Mở `http://<ip-máy-chủ>:8000/admin/`.

## Kết nối từ Nano
Token chỉ hiện **một lần** lúc tạo thiết bị. Đưa vào `/etc/edgeface/sync.env` trên Nano:
```
EDGEFACE_SERVER=https://server.local:8443
EDGEFACE_DEVICE_ID=kiosk-01
EDGEFACE_TOKEN=<token vừa tạo>
EDGEFACE_CA=/etc/edgeface/server_ca.pem
```
rồi `sudo systemctl enable --now edgeface-sync`.

## HTTPS trong LAN
Dữ liệu đi qua đây gồm embedding khuôn mặt, nên **không chạy HTTP trần** ngoài môi trường thử.
Tạo chứng chỉ tự ký và ghim CA ở phía Nano:
```bash
openssl req -x509 -newkey rsa:4096 -nodes -days 825 \
  -keyout server.key -out server_ca.pem -subj "/CN=server.local" \
  -addext "subjectAltName=DNS:server.local,IP:192.168.0.10"
uvicorn server.app:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile server.key --ssl-certfile server_ca.pem
```
Chép `server_ca.pem` sang Nano và trỏ `EDGEFACE_CA` vào đó. Nano **xác minh** chứng chỉ
này; nếu bỏ qua bước ghim CA thì TLS không còn tác dụng chống giả mạo máy chủ.

## Gói model
```bash
tar cf bundle.tar -C models/onnx .      # gồm cả manifest.yaml có sha256 từng file
python -m server.cli sign-bundle --file bundle.tar --version 2026-09-22 --activate
```
Lệnh này tạo `bundle.key` (HMAC-SHA256, quyết định D-24) nếu chưa có. Chép **cùng file
khoá đó** sang Nano tại `/etc/edgeface/bundle.key` với quyền 600; thiết bị dùng nó để
xác minh chữ ký. Nano từ chối gói nếu sai sha256, sai chữ ký, thiếu manifest, hoặc bất kỳ
file nào bên trong không khớp hash trong manifest.

## Sao lưu
`server.db` chứa embedding khuôn mặt và toàn bộ lịch sử. Sao lưu định kỳ, mã hoá ổ lưu,
và **chốt D-22** (giữ embedding trên server bao lâu) trước khi dùng với bệnh nhân thật.

## API
`/docs` có tài liệu OpenAPI tự sinh. Tóm tắt:

| Method | Đường dẫn | Dùng để |
|---|---|---|
| POST | `/api/v1/events` | nhận lô outbox (idempotent theo `event_id`) |
| GET | `/api/v1/gallery?date=&since_version=&recognizer_sha256=` | gallery theo ngày |
| GET | `/api/v1/revocations?since=` | danh sách thu hồi |
| GET | `/api/v1/bundles/latest`, `/api/v1/bundles/{version}/file` | gói model |
| POST | `/api/v1/devices/heartbeat` | báo còn sống |
