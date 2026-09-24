-- One enrolment face crop per patient, so a nurse can tell a duplicate registration
-- apart from a genuine lookalike (C-24, which reverses C-04 for this one case).
--
-- The row hangs off the patient with ON DELETE CASCADE, and foreign keys are enforced
-- (storage/db.py PRAGMA foreign_keys=ON), so the picture disappears the moment the
-- patient does -- at the 24 h expiry, or on a revocation from the server. There is no
-- separate retention path to forget to write.
--
-- A table of its own rather than a column on `patients`: that table is read with
-- SELECT * on every gallery refresh and every patient list, and a 3 KB blob on each row
-- would be carried through all of it for nothing.
CREATE TABLE IF NOT EXISTS patient_faces (
  patient_code TEXT PRIMARY KEY REFERENCES patients(patient_code) ON DELETE CASCADE,
  jpeg         BLOB NOT NULL,          -- 112x112 aligned crop from S6, JPEG
  created_at   REAL NOT NULL,
  expires_at   REAL
);
