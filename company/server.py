"""Local SPMS service. Python standard library only; no cloud connections."""

import argparse
import base64
import json
import ipaddress
import sqlite3
import ssl
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from database import migrate
from errors import APIError
from edit_access import EditGate
from modules.repairs import service as repairs
from modules.repairs import operations


ROOT = Path(__file__).resolve().parent
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def bind_address(value):
    address = ipaddress.IPv4Address(value)
    if not address.is_loopback and not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError('host must be a specific private IPv4 address (not 0.0.0.0 or a public IP)')
    return str(address)


def client_network(value):
    network = ipaddress.IPv4Network(value, strict=True)
    if not any(network.subnet_of(private) for private in PRIVATE_NETWORKS):
        raise ValueError('client subnet must be inside 10/8, 172.16/12 or 192.168/16')
    return network
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
            "modules": {"repairs": 2, "legacy_import": 1, "machines": None},
        }


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    request_queue_size = 32

    def __init__(self, address, database, client_networks=(), tls_context=None):
        host = bind_address(address[0])
        self.lan = not ipaddress.ip_address(host).is_loopback
        self.client_networks = tuple(client_network(str(value)) for value in client_networks)
        if self.lan and not self.client_networks:
            raise ValueError('LAN access requires at least one allowed client subnet')
        self.scheme = 'https' if tls_context else 'http'
        self.database = database
        self.edit_gate = EditGate(Path(database).parent / 'edit-password.json')
        super().__init__((host, address[1]), Handler)
        self.allowed_hosts = {f'{host}:{self.server_port}'}
        if not self.lan:
            self.allowed_hosts.add(f'localhost:{self.server_port}')
        if tls_context:
            # Handshake occurs in the request thread, not the accept loop.
            self.tls_context = tls_context
        else:
            self.tls_context = None

    def verify_request(self, request, client_address):
        address = ipaddress.ip_address(client_address[0])
        return address.version == 4 and (address.is_loopback or any(address in network for network in self.client_networks))

    def finish_request(self, request, client_address):
        request.settimeout(15)
        if self.tls_context:
            try:
                with self.tls_context.wrap_socket(request, server_side=True) as secure:
                    self.RequestHandlerClass(secure, client_address, self)
            except (ssl.SSLError, TimeoutError, ConnectionError):
                return
        else:
            super().finish_request(request, client_address)


class Handler(BaseHTTPRequestHandler):
    def allowed_host(self):
        hosts = self.headers.get_all('Host', [])
        return len(hosts) == 1 and hosts[0] in self.server.allowed_hosts

    def send_json(self, status, payload, head=False):
        self.send_content(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8", head)

    def api_error(self, error):
        if isinstance(error, APIError):
            self.send_json(error.status, {"error": str(error)})
        else:
            self.send_json(503, {"error": "暫時無法取得資料，請稍後重試；若持續失敗請聯絡管理人員"})

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
                payload['access'] = 'lan-allowlist' if self.server.lan else 'localhost-only'
                payload['transport'] = self.server.scheme
                status = 200
            except (sqlite3.Error, TypeError, ValueError, OSError):
                payload, status = {"status": "error", "message": "SQLite unavailable"}, 503
            self.send_content(status, json.dumps(payload).encode("utf-8"),
                              "application/json; charset=utf-8", head)
        elif path.startswith("/api/"):
            try:
                query = parse_qs(parsed.query)
                if path == '/api/edit/status':
                    payload = self.server.edit_gate.status()
                elif path == "/api/modules":
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
        body_read = False
        try:
            expected_origin = f'{self.server.scheme}://{self.headers.get("Host", "")}'
            origins = self.headers.get_all('Origin', [])
            if not self.allowed_host() or (origins and origins != [expected_origin]) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise APIError("不允許跨網站寫入", 403)
            if self.headers.get("X-SPMS-Request") != "1":
                raise APIError("操作驗證失敗，請重新整理頁面後再試", 403)
            if self.headers.get_content_type() != "application/json":
                raise APIError("請使用 JSON 格式", 415)
            if self.headers.get("Transfer-Encoding"):
                raise APIError("不支援此傳輸格式", 400)
            if len(self.headers.get_all('Content-Length', [])) != 1:
                raise APIError('內容長度錯誤', 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise APIError("內容長度錯誤")
            if not 0 < length <= 7 * 1024 * 1024 + 65536:
                raise APIError("內容大小超過限制或為空", 413)
            self.connection.settimeout(10)
            try:
                body_read = True
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError()
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError, TimeoutError):
                raise APIError("JSON 內容錯誤或傳輸逾時")
            if not isinstance(payload, dict):
                raise APIError("JSON 須為物件")
            path = urlsplit(self.path).path
            if path == '/api/edit/unlock' and self.command == 'POST':
                operations.keys(payload, ('password',))
                self.send_json(200, self.server.edit_gate.unlock(payload.get('password')))
                return
            if path == '/api/edit/lock' and self.command == 'POST':
                operations.keys(payload, ())
                self.server.edit_gate.revoke(self.headers.get('X-SPMS-Edit-Token'))
                self.send_json(200, {'locked': True})
                return
            self.server.edit_gate.require(self.headers.get('X-SPMS-Edit-Token'))
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
            # Drain a bounded, well-framed rejected body before closing TLS.
            # Otherwise unread POST bytes may reset the socket and hide the 403.
            if not body_read and not self.headers.get('Transfer-Encoding'):
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) == 1 and lengths[0].isascii() and lengths[0].isdigit():
                    remaining = int(lengths[0]) if len(lengths[0]) < 10 else 0
                    if 0 < remaining <= 7 * 1024 * 1024 + 65536:
                        self.connection.settimeout(2)
                        try:
                            self.rfile.read(remaining)
                        except (OSError, TimeoutError):
                            pass
            self.api_error(error)


def startup_options(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument('--host', help='Specific private IPv4 address; omitted uses approved 10.1.121.135 LAN profile; use 127.0.0.1 for local-only access')
    parser.add_argument('--client-subnet', action='append', default=[], help='Allowed IPv4 CIDR; repeat for multiple IT-approved subnets')
    parser.add_argument('--tls-cert', type=Path, help='IT-issued PEM certificate with IP subjectAltName')
    parser.add_argument('--tls-key', type=Path, help='Protected PEM private key; never package or commit')
    parser.add_argument('--allow-http-lan', action='store_true', help='Explicitly accept plaintext transport on the trusted LAN')
    args = parser.parse_args(argv)
    # User-approved host profile. An explicit --host does not inherit its
    # plaintext acknowledgement or subnet; custom LANs remain explicit.
    if args.host is None:
        args.host = '10.1.121.135'
        if not args.client_subnet:
            args.client_subnet = ['10.1.121.0/24']
        if not args.tls_cert and not args.tls_key:
            args.allow_http_lan = True
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        args.host = bind_address(args.host)
        args.client_subnet = [client_network(value) for value in args.client_subnet]
    except ValueError as error:
        parser.error(str(error))
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error('--tls-cert and --tls-key must be used together')
    args.lan = not ipaddress.ip_address(args.host).is_loopback
    if args.lan and not args.client_subnet:
        parser.error('LAN access requires --client-subnet')
    if args.lan and not args.tls_cert and not args.allow_http_lan:
        parser.error('LAN access requires TLS or explicit --allow-http-lan acknowledgement of plaintext passwords/data')
    return args


def main():
    args = startup_options()
    context = None
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
    database = ROOT / "data" / "spms.sqlite3"
    if args.lan and not EditGate(database.parent / 'edit-password.json').status()['configured']:
        raise SystemExit('Set the edit password with company/edit_access.py before enabling LAN access.')
    initialize_database(database)
    with LocalServer((args.host, args.port), database, args.client_subnet, context) as server:
        print(f"SPMS: {server.scheme}://{args.host}:{args.port}/repairs/", flush=True)
        print(f"SQLite: {database}", flush=True)
        if args.lan:
            print('Allowed client subnets: ' + ', '.join(map(str, args.client_subnet)), flush=True)
            print('LAN only: restrict the firewall to these subnets. No public port forwarding.', flush=True)
            if not context:
                print('WARNING: HTTP is plaintext, including the edit password and records. Use only with IT approval; TLS is recommended.', flush=True)
        print('Stop with Ctrl+C. Keep this host awake. Back up the database regularly.', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
