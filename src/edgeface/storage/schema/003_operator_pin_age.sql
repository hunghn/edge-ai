-- When each operator last changed their PIN.
--
-- The admin screen offers "Đổi mã PIN" with no idea whether it has ever been used. A
-- clinic that shares one kiosk PIN between shifts needs to see how old it is, and the
-- row is the only place that can answer.
--
-- Nullable on purpose: an operator created before this migration has no honest answer,
-- and "chưa đổi lần nào" is what the screen should say rather than a made-up date.
ALTER TABLE operators ADD COLUMN pin_changed_at REAL;
