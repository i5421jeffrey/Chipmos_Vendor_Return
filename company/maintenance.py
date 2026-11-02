"""Offline SQLite backup/verification/recovery. Never overwrite a live database.

Recovery creates a NEW database for review; switching production files is a
separate, stopped-service maintenance action. No network access is performed.
"""
import argparse
import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path


def verify(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        integrity = connection.execute('PRAGMA integrity_check').fetchall()
        if integrity != [('ok',)] or connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite integrity/foreign key check failed')
        versions = connection.execute("SELECT version FROM spms_module_migrations WHERE module='repairs' ORDER BY version").fetchall()
        if versions != [(1,), (2,)]:
            raise ValueError('Expected repairs schema v2; use the matching program for older backups')
        for content, expected in connection.execute('SELECT content,sha256 FROM repair_attachments'):
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError('Attachment SHA256 verification failed')
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_source_files'").fetchone():
            legacy_versions = connection.execute("SELECT version FROM spms_module_migrations WHERE module='legacy_import' ORDER BY version").fetchall()
            if legacy_versions != [(1,)]:
                raise ValueError('Unsupported source archive module version')
            for content, expected in connection.execute('SELECT content,sha256 FROM legacy_source_files'):
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError('Source CSV SHA256 verification failed')
        dbn_table = 'all_dbn_records' if connection.execute("SELECT 1 FROM sqlite_master WHERE name='all_dbn_records'").fetchone() else 'dbn_records'
        return {table: connection.execute('SELECT count(*) FROM ' + (dbn_table if table == 'dbn_records' else table)).fetchone()[0]
                for table in ('repair_records', 'dbn_records', 'serial_board_mappings', 'repair_attachments', 'record_change_history')}


def snapshot(source, destination):
    source, destination = Path(source), Path(destination)
    if not destination.parent.is_dir():
        raise ValueError('Destination directory must already exist')
    # Exclusive creation protects existing files, symlinks and the source itself.
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(destination)) as output:
                original.backup(output)
        return verify(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'verify', 'recover'))
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parent / 'data/spms.sqlite3')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'verify':
            print(verify(args.source))
            return 0
        if not args.output:
            parser.error('--output is required; existing output files are never overwritten')
        print('Source:', args.source.absolute())
        print('NEW output:', args.output.absolute())
        print('Includes Fail Logs inside SQLite. No cloud or program changes.')
        if args.action == 'recover':
            print('Recovery creates a new file only. Stop SPMS before any later manual database switch.')
        if input('Type COPY to confirm, anything else to cancel: ') != 'COPY':
            print('Cancelled. No files written.')
            return 0
        print(snapshot(args.source, args.output))
        print('COPY OK. Original unchanged; verify and retain this file under company backup policy.')
        return 0
    except (OSError, sqlite3.Error, ValueError) as error:
        print('FAILED:', error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('Cancelled.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
