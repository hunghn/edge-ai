"""SQLite access layer shared by the engine, kiosk and sync processes.

Every SQL statement in the project lives here. Processes call functions, never raw SQL,
so no process writes against another process's tables by accident.

Ownership of writes (see docs/plans/M4_database.md §5):
  engine : sessions, kiosk_state, outbox (enqueue), face_templates, evidence, stage_latency
  kiosk  : kiosk_commands, operators (PIN change)
  sync   : outbox (mark sent/failed), patients + templates from the server, revocations,
           model_bundles
"""
