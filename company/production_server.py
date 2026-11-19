"""Approved Flask/Waitress entry point using the existing SPMS database.

The comparison entry point remains isolated. Never import/merge its snapshots.
"""
from pathlib import Path
import sqlite3
from uuid import uuid4

from edit_access import EditGate
from errors import APIError
from flask_server import MAX_BODY, create_app
from maintenance import snapshot
from server import ROOT, initialize_database, startup_options

APPROVED_SUBNETS = ('10.1.121.0/24', '192.168.120.0/24')


def production_options(argv=None):
    # Latest approved default: all sources on the existing IPv4 listener.
    # Explicit host/subnet choices do not silently inherit this wider access.
    return startup_options(argv, source_modes=True, default_subnets=APPROVED_SUBNETS,
                           default_all_sources=True)


def prepare_production_database(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('Existing SPMS database missing; refusing to create an empty database.')
    if not EditGate(source.parent/'edit-password.json').status()['configured']:
        raise ValueError('Existing edit password is not configured; no database changes made.')
    folder = source.parent/'backups'/'flask-startup'/uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    backup = folder/'spms.sqlite3'
    counts = snapshot(source, backup)
    # Backup must finish and verify before applying additive migrations, if any.
    initialize_database(source)
    return source, backup, counts


def main(argv=None):
    args = production_options(argv)
    if args.tls_cert:
        raise SystemExit('This entry point supports HTTP only; use server.py for direct TLS.')
    try:
        from waitress import create_server
        from flask import Flask
    except ImportError:
        raise SystemExit('Install Flask/Waitress into the SPMS venv first; no fallback server started.')
    app = None
    server = None
    try:
        database, backup, counts = prepare_production_database(ROOT/'data/spms.sqlite3')
        app = create_app(database, host=args.host, port=args.port, client_subnets=args.client_subnet,
                         allow_all_sources=args.allow_all_sources)
        server = create_server(app, host=args.host, port=args.port, threads=10,
            connection_limit=100, channel_timeout=15, max_request_body_size=MAX_BODY,
            clear_untrusted_proxy_headers=True, url_scheme='http')
        access_ip = '10.1.121.135' if args.host == '0.0.0.0' else args.host
        print(f'SPMS: http://{access_ip}:{args.port}/repairs/', flush=True)
        print('Listening:', args.host, args.port, flush=True)
        print('LIVE DATABASE:', database, flush=True)
        print('Verified startup backup:', backup, flush=True)
        if args.allow_all_sources:
            print('SOURCE ACCESS: ALL IPv4 sources (no source-IP allowlist).', flush=True)
            print('WARNING: Anyone who can reach this service with an allowed Host can read SPMS data.', flush=True)
        else:
            print('Source allowlist:', ', '.join(map(str, args.client_subnet)) or 'loopback only', flush=True)
        print('Writes are saved to the original database. No test data is imported.', flush=True)
        print('HTTP is plaintext. Shared proxies may allow additional readers. No Proxy/firewall changes.', flush=True)
        print('Keep this window open. Ctrl+C to stop. Do not run another SPMS server concurrently.', flush=True)
        server.run()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, sqlite3.Error, APIError) as error:
        raise SystemExit('SPMS startup/server failed: ' + str(error))
    finally:
        if server is not None:
            server.close()
        if app is not None:
            for handler in app.extensions['spms_diagnostics'].handlers:
                handler.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
