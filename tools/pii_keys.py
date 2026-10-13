"""
The key pair behind customer phone/email encryption (PII policy 2026-10-13).

Phone numbers and emails are stored encrypted with a PUBLIC key (db/pii.sql).
Only the matching PRIVATE key can read them, and it never goes near the server:
it lives in a folder on the admin's machine, outside this repository. Uses
GnuPG (`gpg`, which ships with Git for Windows) - pgcrypto writes standard
OpenPGP messages, which gpg reads.

    python tools/pii_keys.py generate                 # once: make the key pair
    python tools/pii_keys.py install                  # put the PUBLIC key in the database
    python tools/pii_keys.py reveal lead 146297       # admin: decrypt one record's phone/email

  --home DIR   where the key lives (default: %USERPROFILE%\\elite-pii-key).
               Keep it private, and keep a copy of PRIVATE-KEY-backup.asc in a
               password manager: if the private key is lost, every encrypted
               phone number and email is lost with it - there is no recovery.
  --dsn URL    the database (default: DATABASE_URL from .env).

`reveal` reads with a read-only connection and decrypts on THIS machine; the
private key is never sent anywhere. Nothing in the dashboard can decrypt.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HOME = Path(os.environ.get("USERPROFILE") or Path.home()) / "elite-pii-key"
UID = "Elite Motors customer PII <pii-key@elite-dashboard.invalid>"

# Every phone/email column and its encrypted companion (db/pii.sql).
ENCRYPTED = {
    "lead": ("dsr.lead", "lead_id", ["mobile", "email"]),
    "booking": ("dsr.booking", "booking_id", ["mobile"]),
    "test_drive": ("dsr.test_drive", "test_drive_id", ["mobile", "email"]),
    "registration": ("dsr.registration", "registration_id", ["contact_no", "email"]),
    "test_drive_booking": ("dsr.test_drive_booking", "booking_id", ["phone"]),
    "enquiries": ("public.enquiries", "enquiry_id", ["mobile", "email"]),
}


def _gpg() -> str:
    found = shutil.which("gpg")
    for candidate in (found, r"C:\Program Files\Git\usr\bin\gpg.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("gpg was not found. It ships with Git for Windows (Git Bash), or install GnuPG.")


def _home_arg(home: Path, gpg: str) -> str:
    """--homedir as this gpg reads paths. The gpg in Git for Windows is an MSYS
    program: it takes /c/Users/..., and reads C:/Users/... as a relative path."""
    p = home.resolve()
    parts = {x.lower() for x in Path(gpg).parts}
    if {"git", "usr"} <= parts and p.drive:
        return "/" + p.drive[0].lower() + p.as_posix()[2:]
    return str(p)


def _run(home: Path, *args: str, stdin: bytes | None = None) -> bytes:
    gpg = _gpg()
    homedir = _home_arg(home, gpg)
    # gpg-agent talks over a socket file inside the folder, and a socket path
    # has a hard length limit: a deep folder makes key generation and
    # decryption fail with "No agent running".
    if len(homedir) > 80:
        sys.exit(f"The key folder path is too long for gpg ({len(homedir)} characters): "
                 f"{home}. Use a shorter one, e.g. the default {DEFAULT_HOME}.")
    cmd = [gpg, "--homedir", homedir, "--batch", "--quiet", *args]
    res = subprocess.run(cmd, input=stdin, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"gpg {args[0]} failed: {res.stderr.decode(errors='replace').strip()}")
    return res.stdout


def _dsn(arg: str | None) -> str:
    if arg:
        dsn = arg
    else:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        sys.exit("No database: set DATABASE_URL (or .env) or pass --dsn.")
    # Same as tools/migrate.py: the session pooler, not the transaction pooler.
    return dsn.replace("postgres://", "postgresql://", 1).replace(":6543/", ":5432/")


def generate(home: Path) -> None:
    if (home / "public.asc").exists():
        sys.exit(f"A key already exists in {home}. Refusing to overwrite it - the data "
                 f"encrypted with it would become unreadable.")
    home.mkdir(parents=True, exist_ok=True)
    # RSA, because pgcrypto encrypts with RSA or Elgamal keys only (not ECC).
    # No passphrase: the folder itself is the secret - keep it private, and keep
    # the backup file in a password manager.
    params = (
        "%no-protection\n"
        "Key-Type: RSA\nKey-Length: 3072\nKey-Usage: sign\n"
        "Subkey-Type: RSA\nSubkey-Length: 3072\nSubkey-Usage: encrypt\n"
        f"Name-Real: Elite Motors customer PII\nName-Email: pii-key@elite-dashboard.invalid\n"
        "Expire-Date: 0\n%commit\n"
    )
    _run(home, "--gen-key", stdin=params.encode())
    (home / "public.asc").write_bytes(_run(home, "--armor", "--export", UID))
    (home / "PRIVATE-KEY-backup.asc").write_bytes(
        _run(home, "--armor", "--export-secret-keys", UID))
    # Stop the background agent gpg started for this folder.
    gpgconf = shutil.which("gpgconf") or str(Path(_gpg()).with_name("gpgconf.exe"))
    if Path(gpgconf).exists():
        subprocess.run([gpgconf, "--homedir", _home_arg(home, _gpg()), "--kill", "gpg-agent"],
                       capture_output=True)
    print(f"Key pair created in {home}")
    print(f"  public.asc               the PUBLIC key - safe to share; install it with:")
    print(f"                           python tools/pii_keys.py install")
    print(f"  PRIVATE-KEY-backup.asc   the PRIVATE key - copy it into a password manager now.")
    print(f"                           Never commit it, email it, or put it on a server.")


def install(home: Path, dsn: str) -> None:
    import psycopg
    public = (home / "public.asc").read_text(encoding="ascii")
    if "PRIVATE KEY" in public.upper():
        sys.exit("public.asc holds a private key - refusing.")
    with psycopg.connect(dsn, prepare_threshold=None) as cx:
        kid = cx.execute("SELECT dsr.pii_install_key(%s)", (public,)).fetchone()[0]
    print(f"Public key {kid} installed and active. New phone numbers and emails are "
          f"stored encrypted from now on.")


def reveal(home: Path, dsn: str, table: str, row_id: int) -> None:
    import psycopg
    if table not in ENCRYPTED:
        sys.exit(f"Unknown table {table!r}. One of: {', '.join(ENCRYPTED)}")
    rel, pk, cols = ENCRYPTED[table]
    if not (home / "PRIVATE-KEY-backup.asc").exists() and not (home / "pubring.kbx").exists():
        sys.exit(f"No key in {home}. Pass --home to the folder that holds it.")
    select = ", ".join(f"{c}, {c}_enc" for c in cols)
    with psycopg.connect(dsn, autocommit=True, prepare_threshold=None,
                         options="-c default_transaction_read_only=on") as cx:
        row = cx.execute(f"SELECT {select} FROM {rel} WHERE {pk} = %s", (row_id,)).fetchone()
    if row is None:
        sys.exit(f"No {table} with {pk} {row_id}.")
    for i, col in enumerate(cols):
        masked, enc = row[2 * i], row[2 * i + 1]
        if enc is None:
            print(f"{col:<11} {masked or '-':<24} (no encrypted value stored for this record)")
            continue
        plain = _run(home, "--decrypt", stdin=bytes(enc)).decode("utf-8")
        print(f"{col:<11} {plain}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["generate", "install", "reveal"])
    ap.add_argument("table", nargs="?")
    ap.add_argument("row_id", nargs="?", type=int)
    ap.add_argument("--home", type=Path, default=DEFAULT_HOME)
    ap.add_argument("--dsn")
    args = ap.parse_args()
    if args.command == "generate":
        generate(args.home)
    elif args.command == "install":
        install(args.home, _dsn(args.dsn))
    else:
        if not args.table or args.row_id is None:
            ap.error("reveal needs a table and a row id, e.g. reveal lead 146297")
        reveal(args.home, _dsn(args.dsn), args.table, args.row_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
