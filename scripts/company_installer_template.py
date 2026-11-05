"""Offline SPMS program installer. Review and obtain IT approval before use.

This file only copies the listed plain-text program files after confirmation.
It does not run the bundled code, access a database, download anything, change
PowerShell policy, or open firewall ports. See --check for a read-only preview.
"""
import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4


BUNDLE = {}  # BUILD_PAYLOAD


def check_local_path(path):
    """Reject links/junctions so program writes cannot escape to protected data."""
    for candidate in (path, *path.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError(f"Links/junctions are not supported: {candidate}")


def program_target(base, name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or "\\" in name or ":" in name or path.is_absolute()
            or not path.parts or path.parts[0] != "company" or str(path) != name
            or any(part in (".", "..") or part.lower() in ("data", ".venv", "backups", "spms-code-backups")
                   or part.startswith(".") or part.endswith((" ", ".")) for part in path.parts)
            or (path.suffix not in (".py", ".html", ".css", ".js", ".json", ".sql", ".md")
                and name != 'company/start_flask_test.cmd')):
        raise ValueError(f"Invalid program path: {name}")
    target = base.joinpath(*path.parts)
    check_local_path(target)
    if target.exists() and not target.is_file():
        raise ValueError(f"Expected a file, not a directory: {target}")
    return target


def validate_bundle(base):
    check_local_path(base)
    if not base.is_dir():
        raise ValueError("Place install_spms.py in the existing SPMS directory first.")
    files = BUNDLE.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Installer has no payload; download the generated install_spms.py.")
    result = {}
    casefolded = set()
    for name, entry in files.items():
        program_target(base, name)
        if name.casefold() in casefolded:
            raise ValueError("Duplicate Windows program path")
        casefolded.add(name.casefold())
        content = entry["content"].encode("utf-8")
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Damaged payload: {name}")
        result[name] = content
    if sum(map(len, result.values())) > 10 * 1024 * 1024:
        raise ValueError("Unexpectedly large payload")
    if "company/server.py" not in result:
        raise ValueError("Missing company/server.py")
    return result


def atomic_write(target, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".spms-write-", dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def replace_program(staged, target):
    os.replace(staged, target)


def install(base):
    """Only called AFTER the interactive confirmation. Never touches data/.venv."""
    contents = validate_bundle(base)
    lock = base / ".spms-install.lock"
    check_local_path(lock)
    # An interrupted installer may leave this lock. Do not delete it blindly.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        return install_locked(base, contents)
    finally:
        lock.unlink()


def install_locked(base, contents):
    backup_root = base / "spms-code-backups"
    check_local_path(backup_root)
    backup_root.mkdir(exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex
    backup = backup_root / label
    backup.mkdir()
    previous = {}
    # Complete all backups before replacing even one existing program file.
    for name in sorted(contents):
        target = program_target(base, name)
        previous[name] = target.exists()
        if previous[name]:
            destination = backup.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(target.read_bytes())
    (backup / "manifest.json").write_text(json.dumps({
        "version": BUNDLE["version"], "previous_files": previous,
        "note": "Program backup only. No database backup. Stop the service before restoring."
    }, indent=2), encoding="utf-8")
    replaced = []
    try:
        with tempfile.TemporaryDirectory(prefix=".spms-stage-", dir=base) as staging:
            staging = Path(staging)
            for name, content in contents.items():
                staged = staging.joinpath(*PurePosixPath(name).parts)
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(content)
                if hashlib.sha256(staged.read_bytes()).hexdigest() != BUNDLE["files"][name]["sha256"]:
                    raise ValueError(f"Staging verification failed: {name}")
            for name in sorted(contents):
                target = program_target(base, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                replaced.append(name)
                replace_program(staging.joinpath(*PurePosixPath(name).parts), target)
    except BaseException:
        failures = []
        for name in reversed(replaced):
            try:
                target = program_target(base, name)
                if previous[name]:
                    atomic_write(target, backup.joinpath(*PurePosixPath(name).parts).read_bytes())
                else:
                    target.unlink(missing_ok=True)
            except (OSError, ValueError) as error:
                failures.append(str(error))
        if failures:
            print("Rollback incomplete. Keep the service stopped; contact maintenance.")
            print("Backup:", backup)
            for message in failures:
                print(message)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify and preview without writing any files")
    args = parser.parse_args()
    base = Path(__file__).absolute().parent
    try:
        contents = validate_bundle(base)
        print("SPMS offline program installer:", BUNDLE["version"])
        print("Target:", base)
        print("Program files:", len(contents))
        for name in sorted(contents):
            print(" ", name)
        print("Protected: company/data, .venv, and all unlisted files remain unchanged.")
        print("No network access, database changes, policy changes, or automatic startup.")
        if args.check:
            print("CHECK OK. No files were written.")
            return 0
        print("Use only if your company's IT policy permits this installer.")
        print("STOP the SPMS PowerShell service with Ctrl+C before continuing.")
        answer = input("Type INSTALL to confirm, or anything else to cancel: ")
        if answer != "INSTALL":
            print("Cancelled. No files were written.")
            return 0
        backup = install(base)
        print("INSTALL OK. Previous program files backed up to:", backup)
        print("No database was opened or migrated. Start SPMS manually to validate.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("INSTALL FAILED:", error, file=sys.stderr)
        print("Keep existing data. Do not delete the database. Contact maintenance.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Cancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
