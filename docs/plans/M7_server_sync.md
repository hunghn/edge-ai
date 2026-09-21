# M7 — Server tối giản + tiến trình sync

**Trạng thái:** Chưa bắt đầu · **Tuần:** 4–5 · **Phụ thuộc:** M4 (định dạng outbox/gallery) · **Cần Nano:** Không

## 1. Mục tiêu và đầu ra
- **Server** (C-02): một ứng dụng chạy trên PC/laptop trong LAN phòng khám. Server nhận sự kiện từ Nano, cấp gallery bệnh nhân trong ngày, danh sách thu hồi và gói model đã ký, kèm trang web quản trị.
- **Sync:** tiến trình trên Nano (Python 3.6, ~80 MB). Đẩy outbox, kéo dữ liệu, xác minh gói model. Mất mạng không ảnh hưởng kiosk (offline-first).

## 2. Phạm vi
- **Làm:** server FastAPI + SQLite, API v1, web quản trị Jinja2, tiến trình sync, script tạo token và ký bundle, test.
- **Không làm:**
  - tích hợp HIS thật (chỉ import CSV)
  - đa thiết bị phức tạp (có hỗ trợ nhiều token, nhưng không có quản lý nhóm)
  - triển khai cloud

## 3. Server (`server/`, Python ≥ 3.8, không chịu ràng buộc 3.6)

### 3.1 Cấu trúc
```
server/
  app.py                 # FastAPI app, mount /api/v1 và /admin
  settings.py            # đọc biến môi trường: DB URL, secret, đường dẫn bundle
  db.py, models.py       # SQLAlchemy 2.x
  schemas.py             # Pydantic: EventIn, GalleryOut, RevocationOut, BundleOut
  api/{events,gallery,revocations,bundles,devices}.py
  web/{auth,views}.py + web/templates/*.html + web/static/
  cli.py                 # create-admin, create-device (in token 1 lần), import-appointments CSV, sign-bundle
  requirements.txt
  tests/
  docker-compose.yml     # tuỳ chọn
```

### 3.2 Mô hình dữ liệu server
| Bảng | Cột chính |
|---|---|
| `devices` | device_id, name, token_hash, created_at, last_seen_at, last_gallery_version, model_version |
| `patients` | patient_code PK, full_name, birth_year, created_at, revoked_at, revoke_reason |
| `appointments` | appointment_code PK, patient_code, procedure_date, status |
| `face_templates` | id, patient_code, embedding (BLOB), quality, recognizer_sha256, source_device_id, created_at |
| `events` | event_id PK (từ Nano → idempotent), device_id, type, payload JSON, received_at |
| `sessions_log` | session_id PK, device_id, kind, started_at, ended_at, decision, rule_id, top1_code, top1_score, nurse_action, confirmed_code (tách từ event `session.closed` để truy vấn) |
| `spoof_events` | event_id, device_id, session_id, p_real, evidence_sha256, received_at |
| `gallery_versions` | date, version, updated_at |
| `bundles` | version, file_path, sha256, signature, created_at, active |
| `admins` | username, password_hash (bcrypt/argon2), created_at |

### 3.3 API v1
Mọi request từ Nano có `Authorization: Bearer <device token>`; server lưu `sha256(token)`.

| Method | Đường dẫn | Mô tả |
|---|---|---|
| POST | `/api/v1/events` | Body `{device_id, events: [{event_id, type, created_at, payload}]}` (≤ 100). Idempotent theo `event_id`. Trả `{accepted: [...], duplicate: [...], rejected: [{event_id, error}]}`. Xử lý theo type: `enrollment.created` → upsert patient/appointment + templates; `session.closed` → `sessions_log`; `spoof.detected` → `spoof_events` |
| GET | `/api/v1/gallery?date=YYYY-MM-DD&since_version=V` | `304`/`{changed:false}` nếu không đổi; ngược lại `{version, recognizer_sha256, patients: [{code, full_name, birth_year, appointment_code, templates: [{embedding_b64, quality}]}]}`. Chỉ BN có lịch trong `date`, chưa thu hồi, đúng `recognizer_sha256` thiết bị báo |
| GET | `/api/v1/revocations?since=ts` | `[{patient_code, revoked_at, reason}]` |
| GET | `/api/v1/bundles/latest` | `{version, sha256, signature, size, url}` |
| GET | `/api/v1/bundles/{version}/file` | File tar của model ONNX + manifest |
| POST | `/api/v1/devices/heartbeat` | `{gallery_version, model_version, disk_free, uptime, outbox_pending}` |

- **Phiên bản API:** tiền tố `/api/v1`; payload có `schema: 1`.
- **HTTPS trong LAN:** chứng chỉ tự ký, Nano ghim CA (`verify=/etc/edgeface/server_ca.pem`). Hướng dẫn tạo chứng chỉ ghi trong `server/README.md`.

### 3.4 Web quản trị (`/admin`, Jinja2, không cần framework JS)
| Trang | Chức năng |
|---|---|
| Đăng nhập | Session cookie (HttpOnly, SameSite), CSRF token cho form |
| Tổng quan | Số phiên hôm nay theo quyết định, số spoof, trạng thái thiết bị (last seen, outbox pending) |
| Bệnh nhân | Danh sách/tìm kiếm; chi tiết (lịch hẹn, số template, lịch sử phiên); **Thu hồi** |
| Lịch hẹn | Import CSV (`patient_code,full_name,birth_year,appointment_code,procedure_date`), xem theo ngày |
| Phiên nhận dạng | Bảng lọc theo ngày/quyết định/hành động điều dưỡng; xuất CSV (phục vụ chỉ số vận hành ở M9) |
| Sự kiện spoof | Danh sách, p_real, thiết bị |
| Thiết bị | Tạo thiết bị + token (hiện 1 lần), thu hồi token |
| Model bundle | Tải lên, ký, kích hoạt phiên bản |

## 4. Sync trên Nano (`src/edgeface/sync/`, Python 3.6)
```
sync/
  __main__.py   # vòng lặp: upload mỗi upload_interval_s, pull mỗi pull_interval_s (D-26), heartbeat; SIGTERM dừng sạch
  client.py     # requests.Session, timeout (connect, read), header token, verify CA
  uploader.py   # outbox.claim_batch → POST → mark_sent (accepted + duplicate) / mark_failed (lỗi mạng: backoff; rejected: giữ lại + log)
  puller.py     # gallery → một giao dịch: xoá BN nguồn 'server' không còn trong danh sách, upsert BN mới, bump version;
                # revocations → xoá ngay BN + template (kể cả nguồn 'kiosk')
  bundle.py     # tải về /var/lib/edgeface/bundles/tmp → kiểm sha256 + chữ ký (D-24) → giải nén → kiểm sha256 từng file theo manifest
                # → status 'staged'; engine áp dụng khi khởi động lại (không hot-swap)
```
- **Backoff:** lũy thừa có trần + jitter (giá trị trình ở M4 §6).
- **Chuyển giao gallery:** BN tải từ server có `expires_at = now + 24h` (C-04). Enroll tại kiosk vẫn giữ đến khi hết hạn, kể cả khi server chưa trả về.
- **Không bao giờ** xoá outbox chưa gửi vì retention; outbox có giới hạn dung lượng riêng và cảnh báo trên UI-10 khi vượt.
- **Chữ ký bundle (D-24, đề xuất):** `HMAC-SHA256(key, sha256_hex || version)`, khoá chung đặt ở `/etc/edgeface/bundle.key` (quyền 600). Lý do: stdlib Python 3.6 có sẵn; `cryptography` của apt 18.04 không có Ed25519.

## 5. Công việc

| Mã | Công việc |
|---|---|
| M7-T01 | Khung `server/` + settings + DB + migration (Alembic hoặc `create_all` cho đồ án) |
| M7-T02 | Auth thiết bị (token) + `cli.py create-device` |
| M7-T03 | `POST /events` + xử lý 3 loại sự kiện + idempotency |
| M7-T04 | `GET /gallery`, `GET /revocations`, versioning |
| M7-T05 | Bundles: `cli.py sign-bundle`, API tải về |
| M7-T06 | Web: đăng nhập admin, CSRF, layout |
| M7-T07 | Web: bệnh nhân, thu hồi, import CSV lịch hẹn |
| M7-T08 | Web: phiên, spoof, thiết bị, bundles, xuất CSV |
| M7-T09 | `sync/client.py`, `uploader.py` + test với server giả (`http.server` trong test, chạy được trên 3.6) |
| M7-T10 | `sync/puller.py` + test |
| M7-T11 | `sync/bundle.py` + test (sha sai, chữ ký sai, file thiếu → `rejected`) |
| M7-T12 | `deploy/systemd/edgeface-sync.service` |
| M7-T13 | Test end-to-end: server thật (uvicorn local) + sync + DB tạm |
| M7-T14 | `server/README.md`: cài đặt, tạo chứng chỉ, tạo admin/thiết bị, sao lưu DB |

## 6. Giá trị cần xác nhận
- **D-22:** thời gian giữ embedding và log trên server (theo chính sách riêng tư; nên xoá khi hết liệu trình hoặc sau N ngày).
- **D-24:** cơ chế ký bundle.
- **D-26:** chu kỳ pull/upload/heartbeat.
- **D-29:** tài khoản admin.
- **Gallery theo ngày:** mốc đổi ngày (00:00 giờ địa phương?) và có kéo trước lịch của ngày mai vào cuối ngày không.

## 7. Kiểm thử
- **Server:** pytest + `TestClient`:
  - token sai → 401
  - gửi trùng event → `duplicate`
  - payload sai schema → `rejected` nhưng các event khác vẫn nhận
  - gallery chỉ trả BN đúng ngày, chưa thu hồi, đúng `recognizer_sha256`
  - CSRF chặn POST thiếu token
  - import CSV lỗi dòng → báo dòng lỗi, không import nửa chừng
- **Sync:** mất mạng (server tắt) → outbox tích luỹ, `next_attempt_at` tăng; bật lại → gửi hết, không trùng; server trả 500 cho một lô → retry; revocation → BN biến mất khỏi gallery của engine ở phiên kế tiếp.
- **Bảo mật cơ bản:** không log token/embedding; server từ chối HTTP thường khi cấu hình production.
- **End-to-end:** enroll trên kiosk (hoặc `enroll_from_video`) → thấy BN trên web; thu hồi trên web → sau 1 chu kỳ pull, kiosk không còn nhận ra.

## 8. Tiêu chí hoàn thành
- [ ] Test server + sync pass
- [ ] Kịch bản end-to-end ở §7 chạy được giữa PC và Nano trong LAN
- [ ] Tài liệu cài server hoàn chỉnh
- [ ] RAM tiến trình sync trên Nano ≤ ~80 MB

## 9. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| `requests`/`urllib3` trên Python 3.6 thiếu bản vá TLS mới | Pin phiên bản cuối hỗ trợ 3.6; chỉ dùng trong LAN, ghim CA |
| Lệch giờ Nano–server làm sai lọc theo ngày | Server quyết định "hôm nay" theo `date` Nano gửi + cảnh báo khi lệch giờ > 5 phút (so với header `Date` của server) |
| Gallery lớn làm chậm pull | 60 BN × 5 × 512 float32 ≈ 0.6 MB, chưa đáng lo; có `since_version` để bỏ qua khi không đổi |
