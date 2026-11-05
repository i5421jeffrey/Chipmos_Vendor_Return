"""Isolated HTTP transport comparison: Flask/Waitress plus the existing SPMS routes.

The normal server.py stays unchanged. Each CLI start snapshots production into a
new test directory; writes are local to that copy and are never merged back.
"""
import ipaddress
import json
import logging
from email.message import Message
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

from database import utc_now
from edit_access import EditGate
from errors import APIError
from maintenance import snapshot
from server import Handler, ROOT, bind_address, client_network, initialize_database, startup_options

MAX_BODY = 7 * 1024 * 1024 + 65536


def prepare_test_copy(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('Source database missing; stop and check company/data. No empty database created.')
    password = source.parent / 'edit-password.json'
    if not EditGate(password).status()['configured']:
        raise ValueError('Source edit password is not configured. Test copy was not created.')
    folder = source.parent / 'flask-tests' / uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    target = folder / 'spms.sqlite3'
    counts = snapshot(source, target)
    # All migrations (if needed) apply only to this new snapshot.
    initialize_database(target)
    with (folder / 'edit-password.json').open('xb') as stream:
        stream.write(password.read_bytes())
    (folder / 'edit-password.json').chmod(0o600)
    return target, counts


class _Connection:
    def settimeout(self, seconds):
        # Waitress owns socket timeouts; Handler's HTTP framing is already
        # decoded by Waitress into the bounded WSGI input stream.
        pass


def create_app(database, *, host='0.0.0.0', port=8082, client_subnets=('10.1.121.0/24',), diagnostic_log=None):
    from flask import Flask, Response, request
    from werkzeug.exceptions import HTTPException

    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError('Test database must already exist; refusing to create an empty database')
    host = bind_address(host)
    if not 1 <= port <= 65535:
        raise ValueError('Invalid port')
    lan = not ipaddress.ip_address(host).is_loopback
    networks = tuple(client_network(str(value)) for value in client_subnets)
    if lan and not networks:
        raise ValueError('LAN test requires a client subnet allowlist')
    hosts = {f'{host}:{port}'}
    if host == '0.0.0.0':
        hosts = {f'10.1.121.135:{port}', f'127.0.0.1:{port}', f'localhost:{port}'}
    elif not lan:
        hosts.add(f'localhost:{port}')
    state = SimpleNamespace(database=database, edit_gate=EditGate(database.parent/'edit-password.json'),
                            allowed_hosts=hosts, lan=lan, scheme='http', server_port=port)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=MAX_BODY, TESTING=False)
    app.extensions['spms_state'] = state
    logger = logging.Logger('spms-flask-' + uuid4().hex, level=logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(console)
    if diagnostic_log:
        file_handler = logging.FileHandler(diagnostic_log, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(file_handler)
    app.extensions['spms_diagnostics'] = logger

    def log(event, status):
        # No query strings, request bodies, passwords, tokens, cookies, Origin
        # credentials or attachment bytes. JSON escaping prevents log injection.
        logger.info(json.dumps(dict(time=utc_now(), event=event, status=status,
            source=(request.remote_addr or '')[:64], host=request.headers.get('Host','')[:180],
            method=request.method, path=request.path[:240]), ensure_ascii=True))

    class Adapter(Handler):
        """Call the same dispatch/validation code directly, without an HTTP hop."""
        def __init__(self):
            self.server = state
            self.command = request.method
            self.path = request.path
            if request.query_string:
                self.path += '?' + request.query_string.decode('latin-1')
            self.headers = Message()
            for key, value in request.headers.items():
                self.headers[key] = value
            self.rfile = request.stream
            self.connection = _Connection()
            self.response = None

        def send_content(self, status, body, content_type, head=False, headers=None):
            response = Response(b'' if head else body, status=status, content_type=content_type)
            response.headers.update({'Content-Length':str(len(body)), 'Cache-Control':'no-store',
                'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
            response.headers.update(headers or {})
            self.response = response

        def api_error(self, error):
            if self.command in ('POST','PUT','DELETE'):
                log('WRITE_REJECTED', getattr(error,'status',503))
            super().api_error(error)

    @app.before_request
    def guard_source_and_host():
        try:
            address = ipaddress.ip_address(request.remote_addr or '')
            allowed = address.version == 4 and (address.is_loopback or any(address in network for network in networks))
        except ValueError:
            allowed = False
        if not allowed:
            log('SOURCE_DENIED',403)
            return {'error':'不允許此來源位址'},403
        if request.headers.get('Host') not in hosts:
            log('HOST_DENIED',403)
            return {'error':'不允許此主機名稱'},403

    @app.after_request
    def diagnostic_response(response):
        log('RESPONSE',response.status_code)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return {'error': '請求無法處理' if error.code != 413 else '內容大小超過限制'}, error.code

    @app.route('/', defaults={'path':''}, methods=['GET','HEAD','POST','PUT','DELETE','PATCH','OPTIONS'], provide_automatic_options=False)
    @app.route('/<path:path>', methods=['GET','HEAD','POST','PUT','DELETE','PATCH','OPTIONS'], provide_automatic_options=False)
    def dispatch(path):
        adapter = Adapter()
        if request.method in ('GET','HEAD'):
            adapter.serve(head=request.method == 'HEAD')
        elif request.method in ('POST','PUT','DELETE'):
            # WSGI supplies decoded entity bytes, not chunked wire framing.
            # Reject chunked/unknown-size input rather than weakening write rules.
            adapter.write_record()
        else:
            adapter.send_json(405, {'error':'此端點不支援此操作'})
        return adapter.response

    return app


def main(argv=None):
    args = startup_options(argv)
    if args.tls_cert:
        raise SystemExit('This comparison server supports HTTP only; use server.py for direct TLS.')
    try:
        from waitress import create_server
        from flask import Flask
    except ImportError:
        raise SystemExit('Install Flask/Waitress with install_spms_dependencies.py using this venv first.')
    try:
        database, counts = prepare_test_copy(ROOT/'data/spms.sqlite3')
        log_file = database.parent/'connections.jsonl'
        app = create_app(database, host=args.host, port=args.port, client_subnets=args.client_subnet, diagnostic_log=log_file)
        server = create_server(app, host=args.host, port=args.port, threads=10,
            connection_limit=100, channel_timeout=15, max_request_body_size=MAX_BODY,
            clear_untrusted_proxy_headers=True, url_scheme='http')
    except (OSError, ValueError, sqlite3.Error, APIError) as error:
        raise SystemExit('Flask test startup failed: ' + str(error))
    access_ip = '10.1.121.135' if args.host == '0.0.0.0' else args.host
    print(f'Flask + Waitress comparison: http://{access_ip}:{args.port}/repairs/', flush=True)
    if args.host == '0.0.0.0':
        print(f'Local: http://127.0.0.1:{args.port}/repairs/', flush=True)
    print('Listening:', args.host, args.port, flush=True)
    print('TEST COPY ONLY:', database, flush=True)
    print('Source counts:', json.dumps(counts), flush=True)
    print('Connections / denied reasons:', log_file, flush=True)
    print('Source allowlist:', ', '.join(map(str,args.client_subnet)), flush=True)
    print('HTTP is plaintext. No Proxy/firewall changes. Stop original server first.', flush=True)
    print('Each restart creates a NEW snapshot. Test changes are NOT merged into production.', flush=True)
    print('Ctrl+C to stop. server.py remains the original service.', flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        for handler in app.extensions['spms_diagnostics'].handlers:
            handler.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
