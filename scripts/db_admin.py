"""Local database admin CLI (runs on the Nano, Python 3.6).

  python3 scripts/db_admin.py init            --config configs/nano.yaml
  python3 scripts/db_admin.py create-operator --name "Nurse A"
  python3 scripts/db_admin.py stats
  python3 scripts/db_admin.py purge [--dry-run]
  python3 scripts/db_admin.py export-sessions --csv out.csv [--days 7]
  python3 scripts/db_admin.py check
"""
import argparse
import csv
import getpass
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.gallery import retention  # noqa: E402
from edgeface.storage import clock, db, operators, outbox, patients, sessions, templates  # noqa: E402


def db_path(cfg):
    path = cfg_mod.get(cfg, "storage.db_path", "var/edge.db")
    return path if os.path.isabs(path) else os.path.join(REPO, path)


def evidence_dir(cfg):
    path = cfg_mod.get(cfg, "storage.evidence_dir", "var/evidence")
    return path if os.path.isabs(path) else os.path.join(REPO, path)


def cmd_init(conn, cfg, args):
    print("database:", db_path(cfg))
    print("schema version:", db.schema_version(conn))
    print("integrity:", db.integrity_check(conn))
    return 0


def cmd_create_operator(conn, cfg, args):
    pin_length = cfg_mod.get(cfg, "auth.pin_length", 6)
    pin = args.pin or getpass.getpass("PIN ({} digits): ".format(pin_length))
    if not operators.validate_pin_format(pin, pin_length):
        print("PIN must be exactly {} digits".format(pin_length))
        return 2
    if not args.pin:
        if pin != getpass.getpass("Repeat PIN: "):
            print("PINs do not match")
            return 2
    with db.transaction(conn):
        operator_id = operators.create(
            conn, args.name, pin,
            iterations=cfg_mod.get(cfg, "auth.pbkdf2_iterations", 100000),
            pin_length=pin_length)
    print("created operator", operator_id, "-", args.name)
    return 0


def cmd_stats(conn, cfg, args):
    now = clock.now()
    print("database        :", db_path(cfg))
    print("schema version  :", db.schema_version(conn))
    print("patients active :", patients.count_active(conn, now))
    print("templates       :", templates.count(conn))
    print("gallery version :", templates.gallery_version(conn))
    print("operators       :", operators.count(conn))
    print("outbox pending  :", outbox.pending_count(conn),
          "(oldest {:.0f}s)".format(outbox.oldest_pending_age(conn, now)))
    session_stats = sessions.stats(conn, now - 86400.0)
    print("sessions 24h    :", session_stats["total"], session_stats["by_decision"])
    print("nurse actions   :", session_stats["by_nurse_action"])
    return 0


def cmd_purge(conn, cfg, args):
    now = clock.now()
    if args.dry_run:
        expired = conn.execute("SELECT COUNT(*) AS n FROM patients WHERE expires_at <= ?",
                               (now,)).fetchone()["n"]
        revoked = conn.execute("SELECT COUNT(*) AS n FROM revocations").fetchone()["n"]
        old_sessions = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE expires_at <= ?",
                                    (now,)).fetchone()["n"]
        old_evidence = conn.execute("SELECT COUNT(*) AS n FROM evidence WHERE expires_at <= ?",
                                    (now,)).fetchone()["n"]
        print("would delete: patients={} revoked={} sessions={} evidence={}".format(
            expired, revoked, old_sessions, old_evidence))
        return 0
    result = retention.run_once(conn, cfg, now, evidence_dir(cfg), force=args.force)
    for key, value in sorted(result.items()):
        print("  {:20s} {}".format(key, value))
    return 0


def cmd_export_sessions(conn, cfg, args):
    since = clock.now() - args.days * 86400.0
    rows = [row for row in sessions.recent(conn, limit=100000) if row["started_at"] >= since]
    if not rows:
        print("no sessions in the last {} day(s)".format(args.days))
        return 0
    with open(args.csv, "w") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print("wrote {} rows to {}".format(len(rows), args.csv))
    return 0


def cmd_check(conn, cfg, args):
    print("integrity      :", db.integrity_check(conn))
    print("journal mode   :", conn.execute("PRAGMA journal_mode").fetchone()[0])
    print("foreign keys   :", conn.execute("PRAGMA foreign_keys").fetchone()[0])
    print("sqlite version :", conn.execute("SELECT sqlite_version()").fetchone()[0])
    ok, reason, last_run = retention.check_clock(conn, clock.now())
    print("clock guard    :", reason, "(last run {})".format(
        clock.format_ts(last_run) if last_run else "never"))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("init")
    create = sub.add_parser("create-operator")
    create.add_argument("--name", required=True)
    create.add_argument("--pin", help="non-interactive; avoid on a shared machine")
    sub.add_parser("stats")
    purge = sub.add_parser("purge")
    purge.add_argument("--dry-run", action="store_true")
    purge.add_argument("--force", action="store_true", help="ignore the clock guard")
    export = sub.add_parser("export-sessions")
    export.add_argument("--csv", required=True)
    export.add_argument("--days", type=int, default=7)
    sub.add_parser("check")
    args = ap.parse_args()
    if not args.command:
        ap.print_help()
        return 2

    cfg = cfg_mod.load_config(args.config)
    conn = db.open_db(db_path(cfg))
    handlers = {
        "init": cmd_init, "create-operator": cmd_create_operator, "stats": cmd_stats,
        "purge": cmd_purge, "export-sessions": cmd_export_sessions, "check": cmd_check,
    }
    try:
        return handlers[args.command](conn, cfg, args)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
