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
        if exists and connection.execute(
            "SELECT 1 FROM spms_module_migrations WHERE module='repairs' AND version=1"
        ).fetchone():
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
        if connection.execute("SELECT 1 FROM spms_module_migrations WHERE module='repairs' AND version=1").fetchone():
            return
        # Execute DDL inside this transaction, not executescript's implicit commit.
        for statement in (root / "modules/repairs/schema.sql").read_text(encoding="utf-8").split(";"):
            if statement.strip():
                connection.execute(statement)
        catalog = json.loads((root / "modules/repairs/catalog.json").read_text(encoding="utf-8"))
        connection.executemany("INSERT INTO repair_machine_models VALUES (:machine_code, :model)", catalog["machines"])
        connection.executemany("INSERT INTO repair_model_boards VALUES (:model, :board_name, :board_part_code)", catalog["boards"])
        amount_columns = ("board_repair_amount", "external_repair_amount", "contract_repair_amount", "warranty_repair_amount")
        for price in catalog["prices"]:
            amounts = [None if price[key] is None else int(Decimal(str(price[key])) * 100) for key in amount_columns]
            connection.execute("INSERT INTO repair_board_prices VALUES (?,?,?,?,?,?,?)",
                               [price["model"], price["board_name"], price["board_part_code"], *amounts])
        connection.execute("INSERT INTO spms_module_migrations VALUES ('repairs', 1, ?)", (utc_now(),))
