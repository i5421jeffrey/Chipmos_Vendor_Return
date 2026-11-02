"""Build an offline reference catalog from reviewed repository VALUES, not a cloud DB."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(text, marker, columns, terminator):
    values = text.split(marker, 1)[1].split(terminator, 1)[0].strip()
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(f"CREATE TABLE reference ({', '.join(columns)})")
        connection.execute("INSERT INTO reference VALUES " + values)
        return [dict(row) for row in connection.execute("SELECT * FROM reference")]


def build():
    mapping_path = ROOT / "supabase/repair_board_mapping_refresh_20261005.sql"
    prices_path = ROOT / "supabase/repair_board_prices_20261012_migration.sql"
    mapping, prices = mapping_path.read_text(), prices_path.read_text()
    return {
        "sources": [{"file": str(path.relative_to(ROOT)),
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in (mapping_path, prices_path)],
        "machines": rows(mapping, "insert into public.repair_machine_models (machine_code, model) values",
                         ["machine_code TEXT", "model TEXT"], "on conflict"),
        "boards": rows(mapping, "insert into public.repair_model_boards (model, board_name, board_part_code) values",
                       ["model TEXT", "board_name TEXT", "board_part_code TEXT"], "on conflict"),
        "prices": rows(prices, "insert into imported_board_prices values",
                       ["model TEXT", "board_name TEXT", "board_part_code TEXT", "board_repair_amount REAL",
                        "external_repair_amount REAL", "contract_repair_amount REAL", "warranty_repair_amount REAL"], ";"),
    }


if __name__ == "__main__":
    destination = ROOT / "company/modules/repairs/catalog.json"
    destination.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
