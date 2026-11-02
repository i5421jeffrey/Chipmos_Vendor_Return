"""Local SPMS service. Python standard library only; no cloud connections."""

import argparse
import base64
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from database import migrate
from errors import APIError
from modules.repairs import service as repairs
from modules.repairs import operations


ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/repairs/": ("repairs.html", "text/html; charset=utf-8"),
    "/repairs/app.js": ("repairs.js", "text/javascript; charset=utf-8"),
    "/repairs/style.css": ("repairs.css", "text/css; charset=utf-8"),
    "/repairs/features.js": ("features.js", "text/javascript; charset=utf-8"),
    "/repairs/original.css": ("original.css", "text/css; charset=utf-8"),
    "/repairs/parity.css": ("parity.css", "text/css; charset=utf-8"),
}


def initialize_database(path):
    existed = path.exists()
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
    migrate(path, backup_required=existed)


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
            "phase": 3,
            "access": "localhost-only",
            "modules": {"repairs": 2, "machines": None},
        }


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, database):
        self.database = database
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def allowed_host(self):
        return self.headers.get("Host") in (
            f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def send_json(self, status, payload, head=False):
        self.send_content(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8", head)

    def api_error(self, error):
        if isinstance(error, APIError):
            self.send_json(error.status, {"error": str(error)})
        else:
            self.send_json(503, {"error": "本機資料庫暫時無法使用，請稍後重試；若持續失敗請保留資料庫並聯絡維護人員"})

    def send_content(self, status, body, content_type, head=False, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
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
        if not self.allowed_host():
            self.send_json(403, {"error": "不允許此主機名稱"}, head)
            return
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/api/health":
            try:
                payload = database_status(self.server.database)
                status = 200
            except (sqlite3.Error, TypeError, ValueError, OSError):
                payload, status = {"status": "error", "message": "SQLite unavailable"}, 503
            self.send_content(status, json.dumps(payload).encode("utf-8"),
                              "application/json; charset=utf-8", head)
        elif path.startswith("/api/"):
            try:
                query = parse_qs(parsed.query)
                if path == "/api/modules":
                    payload = {"repairs": {"installed": True, "url": "/repairs/", "stage": "local-feature-validation"},
                               "machines": {"installed": False, "url": None}}
                elif path == "/api/repairs/catalog":
                    payload = repairs.catalog(self.server.database)
                elif path == "/api/repairs/serial-mapping":
                    payload = repairs.serial_mapping(self.server.database, query.get("serial", [""])[0])
                elif path == '/api/repairs/serial-summary':
                    payload = operations.serial_summary(self.server.database, query.get('serial', [''])[0])
                elif path == "/api/repairs/records":
                    payload = repairs.list_records(self.server.database, query)
                elif path == '/api/repairs/dbn/catalog':
                    payload = operations.dbn_catalog(self.server.database)
                elif path == '/api/repairs/dbn':
                    payload = operations.list_dbn(self.server.database, query)
                elif path == '/api/repairs/mappings':
                    payload = operations.list_mappings(self.server.database, query)
                elif path == '/api/repairs/history':
                    payload = operations.history(self.server.database, query)
                elif path == '/api/repairs/statistics':
                    payload = operations.statistics(self.server.database, query)
                elif path == '/api/repairs/masters':
                    payload = operations.masters(self.server.database)
                elif path.startswith('/api/repairs/attachments/') and '/' not in path.removeprefix('/api/repairs/attachments/'):
                    attachment = operations.attachment_content(self.server.database, path.removeprefix('/api/repairs/attachments/'))
                    disposition = 'attachment' if query.get('download', [''])[0] == '1' else 'inline'
                    self.send_content(200, attachment['content'], 'text/plain; charset=utf-8', head,
                                      {'Content-Disposition': disposition + "; filename=fail-log.txt; filename*=UTF-8''" + quote(attachment['filename'], safe='')})
                    return
                elif path.startswith("/api/repairs/records/"):
                    record_id = path.removeprefix("/api/repairs/records/")
                    if record_id.endswith("/history"):
                        payload = repairs.list_history(self.server.database, record_id.removesuffix("/history"))
                    elif record_id.endswith('/chain'):
                        payload = operations.chain(self.server.database, record_id.removesuffix('/chain'))
                    elif record_id.endswith('/attachment'):
                        payload = operations.attachment_metadata(self.server.database, record_id.removesuffix('/attachment'))
                    else:
                        payload = repairs.record_detail(self.server.database, record_id)
                else:
                    raise APIError("找不到此功能", 404)
                self.send_json(200, payload, head)
            except (APIError, sqlite3.Error) as error:
                if head:
                    self.send_content(getattr(error, "status", 503), b"", "application/json", True)
                else:
                    self.api_error(error)
        elif path == '/repairs/ghost-logo.png':
            branding = json.loads((ROOT / 'web/branding.json').read_text(encoding='utf-8'))
            self.send_content(200, base64.b64decode(branding['content_base64'], validate=True), 'image/png', head)
        elif path in ASSETS:
            filename, content_type = ASSETS[path]
            self.send_content(200, (ROOT / "web" / filename).read_bytes(), content_type, head)
        else:
            # Serve only explicit UI assets, never database/source/attachment paths.
            self.send_content(404, b"Not found", "text/plain; charset=utf-8", head)

    def do_POST(self):
        self.write_record()

    def do_PUT(self):
        self.write_record()

    def do_DELETE(self):
        self.write_record()

    def write_record(self):
        try:
            origins = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
            if not self.allowed_host() or self.headers.get("Origin", origins[0]) not in origins:
                raise APIError("不允許跨網站寫入", 403)
            if self.headers.get("X-SPMS-Request") != "1":
                raise APIError("缺少本機操作驗證標頭", 403)
            if self.headers.get_content_type() != "application/json":
                raise APIError("請使用 JSON 格式", 415)
            if self.headers.get("Transfer-Encoding"):
                raise APIError("不支援此傳輸格式", 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise APIError("內容長度錯誤")
            if not 0 < length <= 7 * 1024 * 1024 + 65536:
                raise APIError("內容大小超過限制或為空", 413)
            self.connection.settimeout(10)
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError()
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError, TimeoutError):
                raise APIError("JSON 內容錯誤或傳輸逾時")
            if not isinstance(payload, dict):
                raise APIError("JSON 須為物件")
            path = urlsplit(self.path).path
            parts = path.removeprefix('/api/repairs/').split('/') if path.startswith('/api/repairs/') else []
            if self.command == 'POST' and len(parts) == 3 and parts[0] == 'records' and parts[2] in ('resolve', 'attachment'):
                operation = operations.resolve if parts[2] == 'resolve' else operations.upload_attachment
                self.send_json(200, operation(self.server.database, parts[1], payload))
            elif self.command == 'DELETE' and len(parts) == 2 and parts[0] in ('records', 'dbn', 'attachments'):
                self.send_json(200, operations.delete(self.server.database, parts[0], parts[1], payload))
            elif self.command == 'POST' and path == '/api/repairs/mappings/impact':
                self.send_json(200, operations.preview_mapping(self.server.database, payload))
            elif self.command == 'POST' and path == '/api/repairs/mappings':
                self.send_json(200, operations.save_mapping(self.server.database, payload))
            elif self.command == 'POST' and path == '/api/repairs/masters':
                self.send_json(200, operations.save_master(self.server.database, payload))
            elif self.command == 'POST' and path == '/api/repairs/dbn':
                self.send_json(201, operations.save_dbn(self.server.database, payload))
            elif self.command == 'PUT' and len(parts) == 2 and parts[0] == 'dbn':
                self.send_json(200, operations.save_dbn(self.server.database, payload, parts[1]))
            elif self.command == "POST" and path == "/api/repairs/records":
                result = repairs.save_record(self.server.database, payload)
                self.send_json(201, result)
            elif self.command == "PUT" and path.startswith("/api/repairs/records/") and path.removeprefix("/api/repairs/records/") and "/" not in path.removeprefix("/api/repairs/records/"):
                result = repairs.save_record(self.server.database, payload, path.removeprefix("/api/repairs/records/"))
                self.send_json(200, result)
            else:
                raise APIError("此端點不支援寫入", 405)
        except (APIError, sqlite3.Error) as error:
            self.api_error(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    database = ROOT / "data" / "spms.sqlite3"
    initialize_database(database)
    with LocalServer(("127.0.0.1", args.port), database) as server:
        print(f"SPMS local: http://127.0.0.1:{args.port}", flush=True)
        print(f"SQLite: {database}", flush=True)
        print("Local computer only. Stop with Ctrl+C.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
