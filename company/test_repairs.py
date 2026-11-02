import concurrent.futures
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from database import connect
from errors import APIError
from modules.repairs import service
from server import LocalServer, initialize_database


def example(**changes):
    return {"serial_no": "002850948", "machine_code": "F45", "description": "HVDR PE",
            "board_part_code": "BPR-030837", "failure_tag": "RTE", "failure_description": "測試異常",
            "repair_type": "板修", "is_opened": False, "occurred_on": "2026-11-02",
            "sent_on": "", "returned_on": "", "current_status": "待送修", **changes}


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "spms.sqlite3"
        initialize_database(self.path)

    def test_create_search_mapping_and_history(self):
        record = service.save_record(self.path, example(serial_no="2850948"))["data"]
        self.assertEqual(record["serial_no"], "002850948")
        self.assertEqual(record["model"], "T5377S")
        self.assertEqual(record["version"], 1)
        self.assertIs(record["is_opened"], False)
        self.assertEqual(service.list_records(self.path, {"q": ["2850948"]})["total"], 1)
        self.assertEqual(service.list_records(self.path, {"q": ["測試"]})["total"], 1)
        self.assertEqual(service.list_records(self.path, {"q": ["%"]})["total"], 0)
        self.assertEqual(service.list_records(self.path, {"page": ["99"]})["page"], 1)
        with self.assertRaises(APIError):
            service.list_records(self.path, {"page": ["9" * 100]})
        mapping = service.serial_mapping(self.path, "2850948")["data"]
        self.assertEqual(mapping["board_name"], "HVDR PE")
        self.assertNotIn("model", mapping)
        events = service.list_history(self.path, record["id"])["data"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["operation"], "INSERT")

    def test_update_and_stale_version(self):
        record = service.save_record(self.path, example())["data"]
        updated = service.save_record(self.path, example(failure_description="補充描述", expected_version=1), record["id"])["data"]
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["failure_description"], "補充描述")
        with self.assertRaises(APIError) as caught:
            service.save_record(self.path, example(expected_version=1), record["id"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(service.record_detail(self.path, record["id"])["data"]["failure_description"], "補充描述")
        self.assertEqual(len(service.list_history(self.path, record["id"])["data"]), 2)

    def test_concurrent_update_has_one_winner(self):
        record = service.save_record(self.path, example())["data"]
        def edit(number):
            try:
                service.save_record(self.path, example(expected_version=1, failure_description=str(number)), record["id"])
                return 200
            except APIError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(edit, range(2))), [200, 409])

    def test_serial_conflict_does_not_overwrite(self):
        record = service.save_record(self.path, example())["data"]
        with self.assertRaises(APIError) as caught:
            service.save_record(self.path, example(description="I/O PE", board_part_code="BIR-030083"))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(service.list_records(self.path, {})["total"], 1)
        self.assertEqual(service.serial_mapping(self.path, record["serial_no"])["data"]["board_name"], "HVDR PE")

    def test_validation_and_transactions(self):
        invalid = [example(failure_description="  "), example(machine_code="UNKNOWN"),
                   example(description="HVDR PE", board_part_code="BAD"), example(serial_no="\x00"),
                   example(failure_tag="unknown"), example(current_status="結案（PASS）"),
                   example(is_opened="false"), example(occurred_on="2026-02-30"),
                   example(current_status="取回驗證"), example(sent_on="2020-01-01"),
                   example(repair_amount=1), example(model="T5377"), example(returned_on="2026-11-02")]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(APIError):
                service.save_record(self.path, payload)
        with connect(self.path) as connection:
            for table in ("repair_records", "serial_board_mappings", "record_change_history"):
                self.assertEqual(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_amount_zero_unset_and_exact_price(self):
        unset = service.save_record(self.path, example(serial_no="A1", description="ALPG", board_part_code="BIR-030349"))["data"]
        zero = service.save_record(self.path, example(serial_no="A2", repair_type="合約"))["data"]
        priced = service.save_record(self.path, example(serial_no="A3", description="TP6B CPU", board_part_code="WBL-H3610207CPU"))["data"]
        self.assertIsNone(unset["repair_amount"])
        self.assertEqual(zero["repair_amount"], 0)
        self.assertEqual(priced["repair_amount"], 33800)

    def test_no_history_sync_and_restart_preservation(self):
        first = service.save_record(self.path, example())["data"]
        second = service.save_record(self.path, example())["data"]
        service.save_record(self.path, example(expected_version=1, failure_description="另一筆"), second["id"])
        initialize_database(self.path)
        self.assertEqual(service.record_detail(self.path, first["id"])["data"]["version"], 1)
        self.assertEqual(service.list_records(self.path, {})["total"], 2)
        self.assertFalse((self.path.parent / "backups").exists())


class UpgradeTests(unittest.TestCase):
    def test_phase_one_upgrade_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "spms.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE spms_schema_version(version INTEGER PRIMARY KEY CHECK(version=1), created_at TEXT NOT NULL)")
                connection.execute("INSERT INTO spms_schema_version VALUES (1, 'original-time')")
                connection.execute("CREATE TABLE unrelated(value TEXT)")
                connection.execute("INSERT INTO unrelated VALUES ('preserve')")
            initialize_database(path)
            backups = list((path.parent / "backups").glob("*.sqlite3"))
            self.assertEqual(len(backups), 1)
            with connect(backups[0]) as connection:
                self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "preserve")
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='repair_records'").fetchone())
            with connect(path) as connection:
                self.assertEqual(connection.execute("SELECT created_at FROM spms_schema_version").fetchone()[0], "original-time")
                self.assertEqual(connection.execute("SELECT value FROM unrelated").fetchone()[0], "preserve")
            initialize_database(path)
            self.assertEqual(len(list((path.parent / "backups").glob("*.sqlite3"))), 1)

    def test_conflicting_schema_rolls_back_without_dropping_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "spms.sqlite3"
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE repair_machine_models (original_data TEXT)")
                connection.execute("INSERT INTO repair_machine_models VALUES ('keep')")
            with self.assertRaises(sqlite3.OperationalError):
                initialize_database(path)
            with connect(path) as connection:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='spms_module_migrations'").fetchone())
                self.assertEqual(connection.execute("SELECT original_data FROM repair_machine_models").fetchone()[0], "keep")


class RepairHTTPTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "spms.sqlite3"
        initialize_database(self.path)
        self.server = LocalServer(("127.0.0.1", 0), self.path)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, method="GET", payload=None, headers=None):
        defaults = {"Content-Type": "application/json", "X-SPMS-Request": "1"}
        defaults.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        with urlopen(Request(self.base + path, data=body, method=method, headers=defaults), timeout=5) as response:
            return response.status, json.load(response)

    def test_full_http_flow(self):
        self.assertTrue(self.request("/api/repairs/catalog")[1]["machines"])
        status, result = self.request("/api/repairs/records", "POST", example())
        self.assertEqual(status, 201)
        record_id = result["data"]["id"]
        status, result = self.request("/api/repairs/records/" + record_id, "PUT", example(expected_version=1, is_opened=True))
        self.assertTrue(result["data"]["is_opened"])
        self.assertEqual(self.request("/api/repairs/records")[1]["total"], 1)
        self.assertEqual(len(self.request("/api/repairs/records/" + record_id + "/history")[1]["data"]), 2)
        modules = self.request("/api/modules")[1]
        self.assertTrue(modules["repairs"]["installed"])
        self.assertFalse(modules["machines"]["installed"])

    def test_bad_requests_and_cross_origin(self):
        cases = [({"Origin": "http://evil.example"}, 403),
                 ({"Host": "evil.example"}, 403),
                 ({"X-SPMS-Request": ""}, 403),
                 ({"Content-Type": "text/plain"}, 415)]
        for headers, expected in cases:
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as caught:
                self.request("/api/repairs/records", "POST", example(), headers)
            self.assertEqual(caught.exception.code, expected)
            caught.exception.close()
        self.assertEqual(service.list_records(self.path, {})["total"], 0)

    def test_malformed_and_unknown_fields(self):
        for raw in (b"{bad}", b"[]", b"null"):
            request = Request(self.base + "/api/repairs/records", data=raw,
                              headers={"Content-Type": "application/json", "X-SPMS-Request": "1"})
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=5)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/repairs/records", "POST", example(extra="ignored?"))
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
