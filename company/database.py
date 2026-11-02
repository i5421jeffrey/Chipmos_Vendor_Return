"""Shared SQLite connections and additive, backed-up module migrations."""
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sql_instant(column):
    # Internal column names only. PostgreSQL +00 offsets need :00 for SQLite.
    return ("julianday(CASE WHEN substr(" + column + ",-3,1) IN ('+','-') "
            "AND substr(" + column + ",-2) GLOB '[0-9][0-9]' THEN " + column + "||':00' ELSE " + column + " END)")


@contextmanager
def connect(path):
    # Do not recreate a database deleted while the service is running.
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=5)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        with connection:
            yield connection


def migrate(path, backup_required=True):
    root = Path(__file__).resolve().parent
    with connect(path) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='spms_module_migrations'").fetchone()
        versions = {row[0] for row in connection.execute("SELECT version FROM spms_module_migrations WHERE module='repairs'")} if exists else set()
        legacy_versions = {row[0] for row in connection.execute("SELECT version FROM spms_module_migrations WHERE module='legacy_import'")} if exists else set()
        if legacy_versions - {1}:
            raise ValueError('Legacy import module is newer than this program; do not downgrade')
        if versions - {1, 2}:
            raise ValueError("Database is newer than this program; do not downgrade")
        if versions == {1, 2} and legacy_versions == {1}:
            return
        # SQLite backup includes committed WAL contents. Never overwrite a backup.
        if backup_required:
            backup_dir = Path(path).parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            filename = "before-repairs-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex + ".sqlite3"
            with closing(sqlite3.connect(backup_dir / filename)) as destination:
                connection.backup(destination)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS spms_module_migrations (
            module TEXT NOT NULL, version INTEGER NOT NULL, applied_at TEXT NOT NULL,
            PRIMARY KEY (module, version))""")
        versions = {row[0] for row in connection.execute("SELECT version FROM spms_module_migrations WHERE module='repairs'")}
        legacy_versions = {row[0] for row in connection.execute("SELECT version FROM spms_module_migrations WHERE module='legacy_import'")}
        if 1 not in versions:
            run_schema(connection, root / 'modules/repairs/schema.sql')
            catalog = json.loads((root / "modules/repairs/catalog.json").read_text(encoding="utf-8"))
            connection.executemany("INSERT INTO repair_machine_models VALUES (:machine_code, :model)", catalog["machines"])
            connection.executemany("INSERT INTO repair_model_boards VALUES (:model, :board_name, :board_part_code)", catalog["boards"])
            amount_columns = ("board_repair_amount", "external_repair_amount", "contract_repair_amount", "warranty_repair_amount")
            for price in catalog["prices"]:
                amounts = [None if price[key] is None else int(Decimal(str(price[key])) * 100) for key in amount_columns]
                connection.execute("INSERT INTO repair_board_prices VALUES (?,?,?,?,?,?,?)",
                                   [price["model"], price["board_name"], price["board_part_code"], *amounts])
            connection.execute("INSERT INTO spms_module_migrations VALUES ('repairs', 1, ?)", (utc_now(),))
        if 2 not in versions:
            run_schema(connection, root / 'modules/repairs/schema_v2.sql')
            catalog = json.loads((root / 'modules/repairs/dbn_catalog.json').read_text(encoding='utf-8'))
            connection.executemany('INSERT INTO dbn_customers VALUES (?)', [(code,) for code in catalog['customers']])
            connection.executemany('INSERT INTO dbn_valid_combinations VALUES (:customer_code,:product_code,:station_code)', catalog['combinations'])
            for row in catalog['sockets']:
                connection.execute('INSERT INTO dbn_socket_files VALUES (?,?,?,?,?)',
                                   (row['id'], row['product_code'], row['source_filename'], row['dut_count'], json.dumps(row['dut_pins'])))
            connection.execute("INSERT INTO spms_module_migrations VALUES ('repairs', 2, ?)", (utc_now(),))
        if not legacy_versions:
            run_schema(connection, root / 'modules/repairs/schema_legacy.sql')
            connection.execute("INSERT INTO spms_module_migrations VALUES ('legacy_import', 1, ?)", (utc_now(),))


def run_schema(connection, path):
    # Reviewed local DDL only; never execute user-supplied SQL.
    for statement in path.read_text(encoding='utf-8').split(';'):
        if statement.strip():
            connection.execute(statement)
