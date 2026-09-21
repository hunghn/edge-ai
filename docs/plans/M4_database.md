# M4 — Database cục bộ trên Nano (SQLite WAL)

**Trạng thái:** Sẵn sàng làm (mọi giá trị chặn đã chốt) · **Tuần:** 3 · **Phụ thuộc:** M1 · **Cần Nano:** Không

## 1. Mục tiêu và đầu ra
- Một file SQLite duy nhất, dùng chung cho 3 tiến trình `engine`, `kiosk` và `sync`, không cần socket hay hàng đợi.
- Tầng truy cập dữ liệu (`storage/`) là nơi duy nhất chứa SQL; các tiến trình chỉ gọi hàm Python.
- Có migration, retention 24 h, outbox bền vững và IPC giữa engine và kiosk.

## 2. Phạm vi
- **Làm:** schema, migration runner, các repository, retention, test đồng thời nhiều tiến trình.
- **Không làm:** logic phiên (M5), UI (M6), gọi server (M7).

## 3. Ràng buộc kỹ thuật quan trọng
- **SQLite trên Ubuntu 18.04 là bản 3.22.** Python 3.6 dùng thư viện hệ thống này, nên **không có**:
  - `INSERT ... ON CONFLICT DO UPDATE` (UPSERT, từ 3.24): dùng `INSERT OR IGNORE` + `UPDATE`, hoặc `INSERT OR REPLACE` khi an toàn (lưu ý REPLACE xoá dòng cũ và kích hoạt CASCADE).
  - Window functions (3.25), `RETURNING` (3.35), `DROP COLUMN` (3.35), cột generated (3.31).
  - CI trên máy dev phải kiểm tra phiên bản: test có fixture ép dùng cú pháp tương thích 3.22, và một test `grep` chặn các từ khoá trên trong `schema/*.sql` và `storage/*.py`.
- **Python 3.6:** không có `datetime.fromisoformat` (3.7+). Mọi thời gian lưu dạng **epoch giây UTC (REAL)**, chuyển sang giờ địa phương chỉ khi hiển thị.
- **Kết nối:** mỗi tiến trình, mỗi thread có connection riêng; không chia sẻ connection giữa các thread.
- **PRAGMA mỗi connection:** `journal_mode=WAL` (chỉ cần một lần, nhưng đặt lại cũng không hại), `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON`.
- **Giao dịch ghi:** `BEGIN IMMEDIATE`, ngắn gọn; không giữ giao dịch trong lúc chạy suy luận.
- **Checkpoint:** `sync` hoặc retention gọi `PRAGMA wal_checkpoint(TRUNCATE)` định kỳ để file WAL không phình.
- **Đồng hồ:** TTL phụ thuộc giờ hệ thống; Nano phải đồng bộ NTP khi có mạng. Retention bỏ qua (không xoá hàng loạt) nếu phát hiện đồng hồ nhảy lùi hoặc nhảy tới > 24 h so với lần chạy trước, và ghi log.

## 4. Công việc

| Mã | Công việc |
|---|---|
| M4-T01 | `storage/db.py`: `connect(path)`, `transaction(conn)` (context manager `BEGIN IMMEDIATE`/COMMIT/ROLLBACK, retry khi `database is locked` tối đa N lần có backoff), `migrate(conn)` đọc `schema/NNN_*.sql` theo thứ tự, ghi `schema_version` |
| M4-T02 | `storage/schema/001_init.sql`: các bảng ở §5 + index |
| M4-T03 | `storage/clock.py`: `now()` có thể thay thế trong test (đồng hồ giả) |
| M4-T04 | `storage/patients.py`: `upsert_patient`, `upsert_appointment`, `get(code)`, `search(query, limit)` (theo mã hoặc tên, không phân biệt dấu tiếng Việt: lưu thêm cột `name_search` đã bỏ dấu), `list_today()`, `revoke(code, reason)`, `delete(code)` |
| M4-T05 | `storage/templates.py`: `add_templates(code, embeddings, qualities, recognizer_sha256)` (BLOB = `vec.astype('<f4').tobytes()`), `load_gallery_rows(recognizer_sha256)`, `bump_gallery_version()` |
| M4-T06 | `storage/sessions.py`: `open_session(kind)`, `update_session(...)`, `close_session(decision, rule_id, nurse_action, ...)`, `recent(limit)` |
| M4-T07 | `storage/kiosk_ipc.py`: `publish_state(state, guidance, session_id, payload)` (UPDATE dòng id = 1, `seq = seq + 1`), `read_state(after_seq)`, `send_command(type, payload)`, `claim_commands()` (đánh dấu `consumed_at` trong cùng giao dịch) |
| M4-T08 | `storage/outbox.py`: `enqueue(type, payload)`, `claim_batch(n, now)` (lấy `sent_at IS NULL AND next_attempt_at ≤ now`), `mark_sent(ids)`, `mark_failed(id, error, backoff)` |
| M4-T09 | `storage/evidence.py`: `save(session_id, jpeg_bytes)` (ghi file tạm rồi `os.rename`, sha256, `expires_at`), `purge_expired()` |
| M4-T10 | `storage/operators.py`: `create(name, pin)`, `verify(operator_id, pin)` (PBKDF2-HMAC-SHA256 qua `hashlib.pbkdf2_hmac`, salt 16 byte `os.urandom`, so sánh bằng `hmac.compare_digest`), khoá sau N lần sai (D-23) |
| M4-T11 | `storage/models_registry.py`: bảng `model_bundles` (dùng ở M7) |
| M4-T12 | `storage/metrics.py`: `add_latency_batch(rows)`, `purge_older_than(ts)` |
| M4-T13 | `gallery/retention.py`: `run_once(now)` xoá BN hết hạn (CASCADE template/appointment), áp revocation, xoá evidence/log/metrics hết hạn, checkpoint WAL, bump gallery version nếu có thay đổi |
| M4-T14 | `scripts/db_admin.py` (CLI trên Nano): `init`, `create-operator`, `stats`, `purge --dry-run`, `export-sessions --csv` |
| M4-T15 | Test (§8) |

## 5. Schema (`001_init.sql`)
```sql
CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);

CREATE TABLE patients (
  patient_code TEXT PRIMARY KEY,
  full_name    TEXT NOT NULL,
  name_search  TEXT NOT NULL,               -- chữ thường, bỏ dấu
  birth_year   INTEGER,
  source       TEXT NOT NULL CHECK (source IN ('kiosk','server')),
  created_at   REAL NOT NULL,
  expires_at   REAL NOT NULL,               -- created_at + 24h (C-04)
  revoked_at   REAL
);
CREATE INDEX ix_patients_expires ON patients(expires_at);
CREATE INDEX ix_patients_search ON patients(name_search);

CREATE TABLE appointments (
  appointment_code TEXT PRIMARY KEY,
  patient_code     TEXT NOT NULL REFERENCES patients(patient_code) ON DELETE CASCADE,
  procedure_date   TEXT NOT NULL,           -- 'YYYY-MM-DD' giờ địa phương
  status           TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE TABLE face_templates (
  template_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_code       TEXT NOT NULL REFERENCES patients(patient_code) ON DELETE CASCADE,
  embedding          BLOB NOT NULL,         -- 512 x float32 little-endian
  quality            REAL,
  recognizer_sha256  TEXT NOT NULL,
  created_at         REAL NOT NULL
);
CREATE INDEX ix_templates_patient ON face_templates(patient_code);

CREATE TABLE gallery_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE revocations (patient_code TEXT PRIMARY KEY, revoked_at REAL NOT NULL, reason TEXT);

CREATE TABLE operators (
  operator_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name    TEXT NOT NULL,
  pin_hash        TEXT NOT NULL,            -- 'pbkdf2_sha256$iter$salt_hex$hash_hex'
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until    REAL,
  active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE sessions (
  session_id     TEXT PRIMARY KEY,          -- uuid4 hex
  kind           TEXT NOT NULL CHECK (kind IN ('identify','enroll')),
  started_at     REAL NOT NULL,
  ended_at       REAL,
  decision       TEXT,
  rule_id        TEXT,
  top1_code      TEXT, top1_score REAL, top2_code TEXT, top2_score REAL,
  votes          INTEGER, n_good_frames INTEGER,
  min_p_real     REAL, spoof_frames INTEGER,
  nurse_action   TEXT CHECK (nurse_action IN ('confirm','reject','retry','manual','timeout','cancel')),
  confirmed_code TEXT,
  operator_id    INTEGER REFERENCES operators(operator_id),
  expires_at     REAL NOT NULL               -- D-22
);
CREATE INDEX ix_sessions_started ON sessions(started_at);

CREATE TABLE kiosk_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  seq INTEGER NOT NULL, state TEXT NOT NULL, guidance_code TEXT,
  session_id TEXT, payload TEXT, updated_at REAL NOT NULL
);
CREATE TABLE kiosk_commands (
  cmd_id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL, payload TEXT, created_at REAL NOT NULL, consumed_at REAL
);
CREATE INDEX ix_cmd_pending ON kiosk_commands(consumed_at);

CREATE TABLE outbox (
  event_id TEXT PRIMARY KEY, type TEXT NOT NULL, payload TEXT NOT NULL,
  created_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at REAL NOT NULL, sent_at REAL, last_error TEXT
);
CREATE INDEX ix_outbox_pending ON outbox(sent_at, next_attempt_at);

CREATE TABLE evidence (
  evidence_id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
);

CREATE TABLE model_bundles (
  version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, path TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('staged','active','rejected')), installed_at REAL NOT NULL
);

CREATE TABLE stage_latency (ts REAL NOT NULL, session_id TEXT, stage TEXT NOT NULL, ms REAL NOT NULL);
CREATE INDEX ix_latency_ts ON stage_latency(ts);
```
- **Quyền ghi:** mỗi bảng chỉ có một tiến trình ghi chính (ghi trong docstring module):
  - `engine`: sessions, kiosk_state, outbox (enqueue), templates, evidence, metrics
  - `kiosk`: kiosk_commands, operators (đổi PIN), patients (form enroll gửi qua command, **không** ghi trực tiếp)
  - `sync`: outbox (mark), patients/templates nguồn server, revocations, model_bundles
- **Loại sự kiện outbox:** `enrollment.created`, `session.closed`, `spoof.detected`, `patient.revoked_local`, `device.heartbeat`. Payload JSON có `schema: 1`.

## 6. Giá trị cần xác nhận
- ~~D-14~~ → **C-16:** evidence = crop mặt (scale 4.0), JPEG, TTL **7 ngày** (`antispoof.evidence` trong config).
- ~~D-22 (phần Nano)~~ → **C-17:** log phiên và metrics giữ **30 ngày** (`retention.sessions_days`). Phần server vẫn mở.
- ~~D-23~~ → **C-18:** PIN **6 chữ số**, sai **5 lần** khoá **5 phút** (`auth.*`).
- Còn lại: số vòng PBKDF2 tạm để 100 000, phải **đo thời gian verify trên Nano** ở M4 và giảm nếu vượt 0.5 s.
- `outbox` backoff: cơ số, trần, jitter. Đề xuất 5 s × 2^n, trần 10 phút, jitter ±20%; chờ duyệt cùng M7.

## 7. File
- `src/edgeface/storage/{__init__,db,clock,patients,templates,sessions,kiosk_ipc,outbox,evidence,operators,models_registry,metrics}.py`
- `src/edgeface/storage/schema/001_init.sql`
- `src/edgeface/gallery/retention.py`
- `scripts/db_admin.py`
- `tests/unit/test_storage_{db,patients,templates,sessions,kiosk_ipc,outbox,evidence,operators,retention}.py`, `tests/unit/test_storage_concurrency.py`, `tests/unit/test_sql_compat.py`
- Cập nhật `README.md` §2 (thêm các file storage mới)

## 8. Kiểm thử
- **Đơn vị:** mỗi repository thao tác trên DB tạm (`tmp_path`).
- **Retention (đồng hồ giả):** BN tạo lúc t, tại t + 23h59 còn, tại t + 24h01 bị xoá kèm template/appointment; revocation xoá ngay; đồng hồ nhảy lùi thì không xoá.
- **Outbox:** `claim_batch` không trả lại event đã sent; `mark_failed` tăng `next_attempt_at`; enqueue hai lần cùng `event_id` bị từ chối.
- **Kiosk IPC:** `read_state(after_seq)` chỉ trả khi có thay đổi; `claim_commands` từ hai consumer không trùng lệnh.
- **Đồng thời:** `multiprocessing` 3 process trong 30 s:
  - engine giả ghi `kiosk_state` 15 Hz + session + outbox
  - kiosk giả đọc 10 Hz + ghi command
  - sync giả claim/mark outbox 1 Hz

  Assert: 0 lỗi `database is locked` thoát ra ngoài, không mất command, số outbox đã gửi = đã enqueue.
- **Tương thích SQL 3.22:** `test_sql_compat.py` quét từ khoá cấm (§3). Test đồng thời cũng chạy lại trên Nano ở M2/M5.
- `vermin --target=3.6-` cho `storage/`, `gallery/`.

## 9. Tiêu chí hoàn thành
- [ ] Toàn bộ test M4 pass trên máy dev
- [ ] Test đồng thời pass trên Nano (khi có thiết bị)
- [ ] `db_admin.py init` + `create-operator` chạy được
- [ ] README §2 được cập nhật

## 10. Rủi ro
| Rủi ro | Giảm thiểu |
|---|---|
| Thẻ nhớ SD chậm / hỏng do ghi nhiều | `synchronous=NORMAL`, ghi metrics theo lô, cân nhắc SSD USB; kiểm tra `PRAGMA integrity_check` khi khởi động |
| Mất điện giữa giao dịch | WAL đảm bảo atomic; test kill -9 tiến trình ghi rồi mở lại DB |
| Kiosk poll 10 Hz tốn CPU | Chỉ đọc 1 dòng theo `seq`; đo CPU ở M6 |
