-- edgeface local database (SQLite, WAL mode).
-- Target: SQLite 3.22 (Ubuntu 18.04 / JetPack 4.6) — no UPSERT, no window functions,
-- no RETURNING, no generated columns. All timestamps are REAL epoch seconds (UTC).

CREATE TABLE IF NOT EXISTS patients (
  patient_code TEXT PRIMARY KEY,
  full_name    TEXT NOT NULL,
  name_search  TEXT NOT NULL,                 -- lowercase, accents stripped
  birth_year   INTEGER,
  source       TEXT NOT NULL CHECK (source IN ('kiosk', 'server')),
  created_at   REAL NOT NULL,
  expires_at   REAL NOT NULL,                 -- created_at + retention.patients_hours (C-04)
  revoked_at   REAL
);
CREATE INDEX IF NOT EXISTS ix_patients_expires ON patients (expires_at);
CREATE INDEX IF NOT EXISTS ix_patients_search ON patients (name_search);

CREATE TABLE IF NOT EXISTS appointments (
  appointment_code TEXT PRIMARY KEY,
  patient_code     TEXT NOT NULL REFERENCES patients (patient_code) ON DELETE CASCADE,
  procedure_date   TEXT NOT NULL,             -- 'YYYY-MM-DD', local time
  status           TEXT NOT NULL DEFAULT 'scheduled'
);
CREATE INDEX IF NOT EXISTS ix_appt_patient ON appointments (patient_code);
CREATE INDEX IF NOT EXISTS ix_appt_date ON appointments (procedure_date);

CREATE TABLE IF NOT EXISTS face_templates (
  template_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  patient_code      TEXT NOT NULL REFERENCES patients (patient_code) ON DELETE CASCADE,
  embedding         BLOB NOT NULL,            -- 512 x float32, little endian, L2-normalized
  quality           REAL,
  recognizer_sha256 TEXT NOT NULL,            -- embeddings of different models never mix
  created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_templates_patient ON face_templates (patient_code);

CREATE TABLE IF NOT EXISTS gallery_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revocations (
  patient_code TEXT PRIMARY KEY,
  revoked_at   REAL NOT NULL,
  reason       TEXT
);

CREATE TABLE IF NOT EXISTS operators (
  operator_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name    TEXT NOT NULL,
  pin_hash        TEXT NOT NULL,              -- pbkdf2_sha256$iterations$salt_hex$hash_hex
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until    REAL,
  active          INTEGER NOT NULL DEFAULT 1,
  created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id     TEXT PRIMARY KEY,            -- uuid4 hex
  kind           TEXT NOT NULL CHECK (kind IN ('identify', 'enroll')),
  started_at     REAL NOT NULL,
  ended_at       REAL,
  decision       TEXT,
  rule_id        TEXT,
  top1_code      TEXT,
  top1_score     REAL,
  top2_code      TEXT,
  top2_score     REAL,
  votes          INTEGER,
  n_good_frames  INTEGER,
  min_p_real     REAL,
  spoof_frames   INTEGER,
  nurse_action   TEXT CHECK (nurse_action IS NULL OR nurse_action IN
                   ('confirm', 'reject', 'retry', 'manual', 'timeout', 'cancel')),
  confirmed_code TEXT,
  operator_id    INTEGER REFERENCES operators (operator_id),
  expires_at     REAL NOT NULL                -- started_at + retention.sessions_days (C-17)
);
CREATE INDEX IF NOT EXISTS ix_sessions_started ON sessions (started_at);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions (expires_at);

-- Single row (id = 1) written by the engine and polled by the kiosk.
CREATE TABLE IF NOT EXISTS kiosk_state (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  seq           INTEGER NOT NULL,
  state         TEXT NOT NULL,
  guidance_code TEXT,
  session_id    TEXT,
  payload       TEXT,                         -- JSON
  updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kiosk_commands (
  cmd_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  type        TEXT NOT NULL,
  payload     TEXT,                           -- JSON
  session_id  TEXT,
  created_at  REAL NOT NULL,
  consumed_at REAL
);
CREATE INDEX IF NOT EXISTS ix_cmd_pending ON kiosk_commands (consumed_at, cmd_id);

CREATE TABLE IF NOT EXISTS outbox (
  event_id        TEXT PRIMARY KEY,           -- uuid4 hex, idempotency key for the server
  type            TEXT NOT NULL,
  payload         TEXT NOT NULL,              -- JSON
  created_at      REAL NOT NULL,
  attempts        INTEGER NOT NULL DEFAULT 0,
  next_attempt_at REAL NOT NULL,
  sent_at         REAL,
  last_error      TEXT
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox (sent_at, next_attempt_at);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  session_id  TEXT REFERENCES sessions (session_id) ON DELETE SET NULL,
  path        TEXT NOT NULL,
  sha256      TEXT NOT NULL,
  created_at  REAL NOT NULL,
  expires_at  REAL NOT NULL                   -- created_at + antispoof.evidence.ttl_days (C-16)
);
CREATE INDEX IF NOT EXISTS ix_evidence_expires ON evidence (expires_at);

CREATE TABLE IF NOT EXISTS model_bundles (
  version      TEXT PRIMARY KEY,
  sha256       TEXT NOT NULL,
  path         TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('staged', 'active', 'rejected')),
  installed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_latency (
  ts         REAL NOT NULL,
  session_id TEXT,
  stage      TEXT NOT NULL,
  ms         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_latency_ts ON stage_latency (ts);

INSERT OR IGNORE INTO kiosk_state (id, seq, state, updated_at) VALUES (1, 0, 'IDLE', 0.0);
INSERT OR IGNORE INTO gallery_meta (key, value) VALUES ('version', '0');
