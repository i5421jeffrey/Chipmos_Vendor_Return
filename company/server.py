"""Phase-one local-only SPMS service. Python standard library only."""

import argparse
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def initialize_database(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=5)) as connection, connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS spms_schema_version (
                version INTEGER PRIMARY KEY CHECK (version = 1),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute(
            "INSERT OR IGNORE INTO spms_schema_version (version) VALUES (1)"
        )


def database_status(path):
    # A status request must never silently create a missing database.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
        version, created_at = connection.execute(
            "SELECT version, created_at FROM spms_schema_version WHERE version = 1"
        ).fetchone()
        return {
            "status": "ok",
            "database": "SQLite",
            "sqlite_version": sqlite3.sqlite_version,
            "schema_version": version,
            "initialized_at": created_at,
            "phase": 1,
            "access": "localhost-only",
        }


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database):
        self.database = database
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def send_content(self, status, body, content_type, head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self):
        self.serve()

    def do_HEAD(self):
        self.serve(head=True)

    def serve(self, head=False):
        path = urlsplit(self.path).path
        if path == "/api/health":
            try:
                payload = database_status(self.server.database)
                status = 200
            except (sqlite3.Error, TypeError, ValueError, OSError):
                payload, status = {"status": "error", "message": "SQLite unavailable"}, 503
            self.send_content(status, json.dumps(payload).encode("utf-8"),
                              "application/json; charset=utf-8", head)
        elif path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_content(200, (ROOT / "web" / filename).read_bytes(), content_type, head)
        else:
            # Serve only explicit UI assets, never database/source/attachment paths.
            self.send_content(404, b"Not found", "text/plain; charset=utf-8", head)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    database = ROOT / "data" / "spms.sqlite3"
    initialize_database(database)
    with LocalServer(("127.0.0.1", args.port), database) as server:
        print(f"SPMS phase 1: http://127.0.0.1:{args.port}", flush=True)
        print(f"SQLite: {database}", flush=True)
        print("Local computer only. Stop with Ctrl+C.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
