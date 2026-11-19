"""Production-mode regression tests use synthetic temporary databases only."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from edit_access import configure
from flask_server import create_app, prepare_test_copy
from modules.repairs import service
from production_server import APPROVED_SUBNETS, main, prepare_production_database, production_options
from server import initialize_database
from test_repairs import example


class ProductionTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('flask') and importlib.util.find_spec('waitress'),
                         'Optional Flask/Waitress not installed')
    def test_main_serves_original_database_with_approved_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'data').mkdir()
            path = root/'data/spms.sqlite3'
            initialize_database(path)
            configure(path.parent/'edit-password.json', 'synthetic-only')
            with patch('production_server.ROOT', root), patch('waitress.create_server') as factory:
                self.assertEqual(main([]), 0)
                app = factory.call_args.args[0]
                self.assertEqual(app.extensions['spms_state'].database, path.resolve())
                self.assertTrue(app.extensions['spms_state'].allow_all_sources)
                self.assertEqual(factory.call_args.kwargs['host'], '0.0.0.0')
                self.assertEqual(factory.call_args.kwargs['port'], 8082)
                self.assertTrue(factory.call_args.kwargs['clear_untrusted_proxy_headers'])
                factory.return_value.run.assert_called_once()
                factory.return_value.close.assert_called_once()
            self.assertFalse((path.parent/'flask-tests').exists())
            self.assertEqual(len(list((path.parent/'backups/flask-startup').glob('*/spms.sqlite3'))), 1)

    def test_approved_defaults_and_explicit_overrides(self):
        args = production_options([])
        self.assertEqual(args.host, '0.0.0.0')
        self.assertEqual(args.port, 8082)
        self.assertTrue(args.allow_http_lan)
        self.assertTrue(args.allow_all_sources)
        self.assertEqual(args.client_subnet, [])
        restricted = production_options(['--restrict-sources'])
        self.assertFalse(restricted.allow_all_sources)
        self.assertEqual(tuple(map(str, restricted.client_subnet)), APPROVED_SUBNETS)
        self.assertTrue(production_options(['--allow-all-sources']).allow_all_sources)
        self.assertEqual(production_options(['--port', '8089']).port, 8089)
        self.assertEqual(production_options(['--host', '127.0.0.1']).client_subnet, [])
        self.assertFalse(production_options(['--host', '127.0.0.1']).allow_all_sources)
        args = production_options(['--client-subnet', '10.1.121.0/24'])
        self.assertEqual(list(map(str, args.client_subnet)), ['10.1.121.0/24'])
        self.assertFalse(args.allow_all_sources)
        self.assertFalse(production_options(['--client-subnet=192.168.120.0/24']).allow_all_sources)
        explicit = production_options(['--host', '10.1.121.135', '--allow-all-sources', '--allow-http-lan'])
        self.assertTrue(explicit.allow_all_sources)
        with self.assertRaises(SystemExit):
            production_options(['--host', '10.1.121.135'])
        for values in (['--allow-all-sources', '--restrict-sources'],
                       ['--allow-all-sources', '--client-subnet', '10.1.121.0/24'],
                       ['--host', '10.1.121.135', '--allow-all-sources']):
            with self.assertRaises(SystemExit):
                production_options(values)

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Optional Flask not installed')
    def test_all_sources_keep_host_origin_edit_and_proxy_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'spms.sqlite3'
            initialize_database(path)
            configure(path.parent/'edit-password.json', 'synthetic-only')
            app = create_app(path, client_subnets=(), allow_all_sources=True)
            self.addCleanup(lambda: [handler.close() for handler in app.extensions['spms_diagnostics'].handlers])
            client = app.test_client()
            def call(route, source='172.16.5.40', method='GET', data=None, headers=None):
                return client.open(route, method=method, json=data, headers=headers or {},
                    base_url='http://10.1.121.135:8082', environ_overrides={'REMOTE_ADDR':source})
            for source in ('10.1.121.40', '192.168.120.89', '172.16.5.40', '203.0.113.40', '127.0.0.1'):
                health = call('/api/health', source)
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json['access'], 'all-ipv4-sources')
                self.assertEqual(call('/repairs/', source).status_code, 200)
                self.assertEqual(call('/api/repairs/records', source).status_code, 200)
            for source in ('::1', '', 'not-an-address'):
                self.assertEqual(call('/api/health', source).status_code, 403)
            self.assertEqual(call('/api/health', headers={'Host':'evil.example:8082',
                'X-Forwarded-Host':'10.1.121.135:8082'}).status_code, 403)
            for host in ('10.1.121.135:8082', 'localhost:8082', '127.0.0.1:8082'):
                self.assertEqual(call('/api/health', headers={'Host':host}).status_code, 200)
            headers = {'X-SPMS-Request':'1'}
            self.assertEqual(call('/api/repairs/records', method='POST', data=example(), headers=headers).status_code, 401)
            self.assertEqual(call('/api/edit/unlock', method='POST', data={'password':'synthetic-only'},
                headers={**headers, 'Origin':'http://evil.example', 'X-Forwarded-Host':'evil.example'}).status_code, 403)
            self.assertEqual(call('/api/edit/unlock', method='POST', data={'password':'synthetic-only'},
                headers={**headers, 'Sec-Fetch-Site':'cross-site'}).status_code, 403)
            unlock = call('/api/edit/unlock', method='POST', data={'password':'synthetic-only'}, headers=headers)
            self.assertEqual(unlock.status_code, 200)
            headers['X-SPMS-Edit-Token'] = unlock.json['token']
            self.assertEqual(call('/api/repairs/records', method='POST', data=example(), headers=headers).status_code, 201)
            call('/api/edit/lock', method='POST', data={}, headers=headers)
            self.assertEqual(call('/api/repairs/records', method='POST', data=example(serial_no='123456789'), headers=headers).status_code, 401)
            self.assertEqual(service.list_records(path, {})['total'], 1)
            with self.assertRaises(ValueError):
                create_app(path, allow_all_sources=True, client_subnets=APPROVED_SUBNETS)

    def test_missing_database_password_and_failed_backup_stop_before_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'spms.sqlite3'
            with self.assertRaises(ValueError):
                prepare_production_database(path)
            self.assertFalse(path.exists())
            initialize_database(path)
            with self.assertRaises(ValueError):
                prepare_production_database(path)
            configure(path.parent/'edit-password.json', 'synthetic-only')
            with patch('production_server.snapshot', side_effect=OSError('disk full')), \
                 patch('production_server.initialize_database') as migrate:
                with self.assertRaises(OSError):
                    prepare_production_database(path)
                migrate.assert_not_called()

    def test_original_identity_backups_and_no_test_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'spms.sqlite3'
            initialize_database(path)
            configure(path.parent/'edit-password.json', 'synthetic-only')
            password = (path.parent/'edit-password.json').read_bytes()
            service.save_record(path, example())
            test_copy, _ = prepare_test_copy(path)
            service.save_record(test_copy, example(serial_no='123456789'))
            database, backup, counts = prepare_production_database(path)
            self.assertEqual(database, path.resolve())
            self.assertEqual(counts['repair_records'], 1)
            service.save_record(database, example(serial_no='987654321'))
            self.assertEqual(service.list_records(backup, {})['total'], 1)
            database2, backup2, counts2 = prepare_production_database(path)
            self.assertEqual(database2, database)
            self.assertNotEqual(backup2, backup)
            self.assertEqual(counts2['repair_records'], 2)
            self.assertEqual((path.parent/'edit-password.json').read_bytes(), password)

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Optional Flask not installed')
    def test_approved_networks_edit_gate_and_live_write_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'spms.sqlite3'
            initialize_database(path)
            configure(path.parent/'edit-password.json', 'synthetic-only')
            database, _, _ = prepare_production_database(path)
            app = create_app(database, client_subnets=APPROVED_SUBNETS)
            self.addCleanup(lambda: [handler.close() for handler in app.extensions['spms_diagnostics'].handlers])
            client = app.test_client()
            def call(route, source='192.168.120.89', method='GET', data=None, headers=None):
                return client.open(route, method=method, json=data, headers=headers or {},
                    base_url='http://10.1.121.135:8082', environ_overrides={'REMOTE_ADDR':source})
            for source in ('10.1.121.40', '192.168.120.1', '192.168.120.254'):
                self.assertEqual(call('/api/health', source).status_code, 200)
            for source in ('192.168.121.89', '10.1.122.40'):
                self.assertEqual(call('/api/health', source).status_code, 403)
            self.assertEqual(call('/api/health', headers={'Host':'evil.example:8082'}).status_code, 403)
            headers = {'X-SPMS-Request':'1'}
            self.assertEqual(call('/api/repairs/records', method='POST', data=example(), headers=headers).status_code, 401)
            unlock = call('/api/edit/unlock', method='POST', data={'password':'synthetic-only'}, headers=headers)
            self.assertEqual(unlock.status_code, 200)
            headers['X-SPMS-Edit-Token'] = unlock.json['token']
            self.assertEqual(call('/api/repairs/records', method='POST', data=example(), headers=headers).status_code, 201)
            self.assertEqual(service.list_records(path, {})['total'], 1)
            self.assertFalse((path.parent/'flask-tests').exists())


if __name__ == '__main__':
    unittest.main()
