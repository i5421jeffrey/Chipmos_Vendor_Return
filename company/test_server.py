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

from server import LocalServer, database_status, initialize_database


class LocalServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "data" / "spms.sqlite3"
        initialize_database(self.database)
        self.server = LocalServer(("127.0.0.1", 0), self.database)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_home_assets_and_headers(self):
        for path in ("/", "/index.html", "/style.css", "/app.js", "/repairs/", "/repairs/style.css", "/repairs/app.js"):
            with urlopen(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
                self.assertTrue(response.read())

    def test_health(self):
        with urlopen(self.base + "/api/health", timeout=5) as response:
            data = json.load(response)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "SQLite")
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["access"], "localhost-only")
        self.assertNotIn(str(self.database), json.dumps(data))

    def test_initialization_preserves_data(self):
        before = database_status(self.database)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE test_persistence (value TEXT)")
            connection.execute("INSERT INTO test_persistence VALUES ('retained')")
        initialize_database(self.database)
        self.assertEqual(before, database_status(self.database))
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM test_persistence").fetchone()[0], "retained")

    def test_private_paths_not_served(self):
        for path in ("/data/spms.sqlite3", "/server.py", "/../server.py", "/%2e%2e/server.py", "/api/unknown"):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base + path, timeout=5)
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()

    def test_writes_not_exposed(self):
        request = Request(self.base + "/api/health", data=b"{}", method="POST")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_head(self):
        with urlopen(Request(self.base + "/", method="HEAD"), timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")

    def test_parallel_status_requests(self):
        def read_status(_):
            with urlopen(self.base + "/api/health", timeout=5) as response:
                return json.load(response)["status"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(read_status, range(12))), ["ok"] * 12)

    def test_missing_database_is_not_recreated(self):
        missing = Path(self.folder.name) / "absent.sqlite3"
        self.server.database = missing
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/api/health", timeout=5)
        self.assertEqual(caught.exception.code, 503)
        caught.exception.close()
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
