"""Server administration from the command line.

  python -m server.cli create-admin --username admin
  python -m server.cli create-device --id kiosk-01 --name "Kiosk tiền thủ thuật"
  python -m server.cli sign-bundle --file bundle.tar --version 2026-09-22
  python -m server.cli import-appointments --csv today.csv
"""
import argparse
import getpass
import hashlib
import os
import sys

from server.api.gallery import sign_bundle
from server.auth import hash_password
from server.db import bump_gallery_version, create_all, hash_token, new_token, session_scope
from server.models import Admin, Bundle, Device
from server.settings import settings


def read_or_create_key(path):
    """The HMAC key both sides use for model bundles (D-24)."""
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    key = os.urandom(32).hex().encode("ascii")
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "wb") as f:
        f.write(key)
    os.chmod(path, 0o600)
    print("created a new bundle key at", path, "- copy it to the device")
    return key


def cmd_create_admin(args):
    password = args.password or getpass.getpass("Password: ")
    if not args.password and password != getpass.getpass("Repeat: "):
        print("passwords do not match")
        return 2
    with session_scope() as session:
        session.merge(Admin(username=args.username, password_hash=hash_password(password)))
    print("admin created:", args.username)
    return 0


def cmd_create_device(args):
    token = new_token()
    with session_scope() as session:
        session.merge(Device(device_id=args.id, name=args.name, token_hash=hash_token(token)))
    print("device:", args.id)
    print("token (shown once):", token)
    print("put it in /etc/edgeface/sync.env on the Nano as EDGEFACE_TOKEN=...")
    return 0


def cmd_sign_bundle(args):
    with open(args.file, "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    key = read_or_create_key(settings.bundle_key_path)
    signature = sign_bundle(digest, args.version, key)
    if not os.path.isdir(settings.bundle_dir):
        os.makedirs(settings.bundle_dir)
    destination = os.path.join(settings.bundle_dir, os.path.basename(args.file))
    if os.path.abspath(destination) != os.path.abspath(args.file):
        with open(destination, "wb") as f:
            f.write(data)
    with session_scope() as session:
        if args.activate:
            for bundle in session.query(Bundle).filter(Bundle.active.is_(True)).all():
                bundle.active = False
        session.merge(Bundle(version=args.version, file_path=destination, sha256=digest,
                             signature=signature, size=len(data), active=args.activate))
    print("bundle {}: sha256={} signature={}".format(args.version, digest[:16], signature[:16]))
    return 0


def cmd_import_appointments(args):
    from server.web.views import parse_appointments_csv
    from server.models import Appointment, Patient

    with open(args.csv, "rb") as f:
        rows, errors = parse_appointments_csv(f.read())
    if errors:
        for error in errors:
            print("error:", error)
        return 2
    dates = set()
    with session_scope() as session:
        for row in rows:
            patient = session.get(Patient, row["patient_code"])
            if patient is None:
                session.add(Patient(patient_code=row["patient_code"],
                                    full_name=row["full_name"], birth_year=row["birth_year"]))
            if row["appointment_code"]:
                date = row["procedure_date"]
                session.merge(Appointment(appointment_code=row["appointment_code"],
                                          patient_code=row["patient_code"],
                                          procedure_date=date))
                dates.add(date)
        for date in dates:
            bump_gallery_version(session, date)
    print("imported {} rows for {} date(s)".format(len(rows), len(dates)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    admin = sub.add_parser("create-admin")
    admin.add_argument("--username", required=True)
    admin.add_argument("--password")
    device = sub.add_parser("create-device")
    device.add_argument("--id", required=True)
    device.add_argument("--name", required=True)
    bundle = sub.add_parser("sign-bundle")
    bundle.add_argument("--file", required=True)
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--activate", action="store_true")
    appointments = sub.add_parser("import-appointments")
    appointments.add_argument("--csv", required=True)

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 2
    create_all()
    return {"create-admin": cmd_create_admin, "create-device": cmd_create_device,
            "sign-bundle": cmd_sign_bundle,
            "import-appointments": cmd_import_appointments}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
