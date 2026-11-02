import base64
import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from database import connect, run_schema
from errors import APIError
from maintenance import snapshot, verify
from modules.repairs import operations as ops, service
from server import initialize_database
import test_repairs as basic
from test_repairs import example


def dbn(**changes):
    return dict(serial_no='2850948', machine_code='F45', board_name='HVDR PE', board_part_code='BPR-030837',
                customer_code='AB', product_code='JAA118', station_code='CP1', issue_type='Group', dut='1-4', **changes)


def upload(content=b'<script>plain text only</script>', filename='test.asc'):
    return dict(filename=filename, content_base64=base64.b64encode(content).decode())


class FeatureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'spms.sqlite3'
        initialize_database(self.path)

    def ready(self, **changes):
        row = service.save_record(self.path, example(**changes))['data']
        return service.save_record(self.path, example(**changes, expected_version=1, current_status='取回驗證', sent_on='2026-11-02', returned_on='2026-11-02'), row['id'])['data']

    def test_dbn_catalog_and_cascade(self):
        catalog = ops.dbn_catalog(self.path)
        self.assertEqual(catalog['customers'], ['AB', 'QR', 'VB'])
        self.assertEqual(len([row for row in catalog['combinations'] if row['customer_code'] == 'QR']), 42)
        self.assertEqual({row['product_code'] for row in catalog['sockets']}, {'JAA118','GAA112','CAA100','GAA126'})
        for payload in (dict(dbn(), station_code='CP99'), dict(dbn(), customer_code='VB'), dict(dbn(), customer_code='BAD')):
            with self.assertRaises(APIError):
                ops.save_dbn(self.path, payload)
        row = ops.save_dbn(self.path, dict(dbn(), customer_code='VB', product_code=None, station_code=None))['data']
        self.assertIsNone(row['socket_file_id'])

    def test_quick_summary_covers_all_pages_and_model_tag_search(self):
        for index in range(21):
            service.save_record(self.path, example(machine_code='F45' if index < 20 else 'F46'))
        ops.save_dbn(self.path, dbn())
        summary = ops.serial_summary(self.path, '2850948')
        self.assertEqual(summary['machines'], ['F45','F46'])
        self.assertEqual(summary['models'], ['T5377S'])
        self.assertEqual(summary['mapping']['board_name'], 'HVDR PE')
        self.assertEqual(service.list_records(self.path, {'q':['T5377S']})['total'], 21)
        self.assertEqual(service.list_records(self.path, {'q':['RTE']})['total'], 21)
        self.assertEqual(service.list_records(self.path, {'q':['板修']})['total'], 21)

    def test_history_filters_taipei_boundaries_and_change_search(self):
        with connect(self.path) as connection:
            for index, stamp in enumerate(('2026-11-01T15:59:59Z', '2026-11-01T16:00:00Z', '2026-11-02T15:59:59Z', '2026-11-02T16:00:00Z')):
                service.audit(connection, 'repair_records', str(index), 'UPDATE', {'failure_description':'old'}, {'failure_description':'unique%_text'})
                connection.execute('UPDATE record_change_history SET changed_at=? WHERE record_id=?', (stamp, str(index)))
        query = {'source':['repair_records'], 'operation':['UPDATE'], 'start':['2026-11-02'], 'end':['2026-11-02'], 'q':['unique%_text']}
        result = ops.history(self.path, query)
        self.assertEqual(result['total'], 2)
        self.assertEqual({row['record_id'] for row in result['data']}, {'1','2'})
        self.assertEqual(ops.history(self.path, dict(query, operation=['DELETE']))['total'], 0)
        self.assertEqual(ops.history(self.path, dict(query, source=['dbn_records']))['total'], 0)
        self.assertEqual(ops.history(self.path, dict(query, end=['9999-12-31']))['total'], 3)
        for invalid in ({'source':['bad']}, {'operation':['bad']}, {'start':['2026-02-30']}, {'end':['11/02']}, {'start':['2026-11-03'], 'end':['2026-11-02']}):
            with self.assertRaises(APIError):
                ops.history(self.path, invalid)

    def test_dbn_snapshot_is_historical(self):
        row = ops.save_dbn(self.path, dbn())['data']
        self.assertEqual(row['serial_no'], '002850948')
        self.assertEqual(len(row['dut_pin_snapshot']), 4)
        self.assertIn('PPS137', row['dut_pin_snapshot']['1'])
        with connect(self.path) as connection:
            connection.execute("UPDATE dbn_socket_files SET dut_pins='{}' WHERE product_code='JAA118'")
        updated = ops.save_dbn(self.path, dict(dbn(), expected_version=1), row['id'])['data']
        self.assertEqual(updated['dut_pin_snapshot'], row['dut_pin_snapshot'])
        self.assertEqual(service.list_records(self.path, {})['total'], 0)
        self.assertEqual(ops.list_dbn(self.path, {'serial':['2850948']})['total'], 1)
        with self.assertRaises(APIError):
            ops.save_dbn(self.path, dict(dbn(), expected_version=1), row['id'])

    def test_dbn_dut_and_issue_validation(self):
        bad = [dict(dbn(), dut='0'), dict(dbn(), dut='4-1'), dict(dbn(), dut='1-9'), dict(dbn(), dut='513'),
               dict(dbn(), issue_type='Single Dut', dut='1-1'), dict(dbn(), issue_type='RTE'), dict(dbn(), issue_type='OTHER'),
               dict(dbn(), dut='1,2'), dict(dbn(), serial_no='\n')]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(APIError):
                ops.save_dbn(self.path, payload)
        row = ops.save_dbn(self.path, dict(dbn(), issue_type='Other', issue_description='發熱'))['data']
        self.assertEqual(row['issue_description'], '發熱')
        self.assertIsNone(row['dut'])

    def test_dbn_mapping_conflict_and_version_delete(self):
        row = ops.save_dbn(self.path, dbn())['data']
        with self.assertRaises(APIError):
            ops.save_dbn(self.path, dict(dbn(), board_name='I/O PE', board_part_code='BIR-030083'))
        with self.assertRaises(APIError):
            ops.delete(self.path, 'dbn', row['id'], {'expected_version':2})
        ops.delete(self.path, 'dbn', row['id'], {'expected_version':1})
        self.assertEqual(ops.list_dbn(self.path, {})['total'], 0)
        self.assertTrue(service.serial_mapping(self.path, row['serial_no'])['data'])
        self.assertTrue(any(event['operation'] == 'DELETE' for event in ops.history(self.path, {})['data']))

    def test_atomic_create_and_attachment(self):
        row = service.save_record(self.path, example(attachment=upload()))['data']
        meta = ops.attachment_metadata(self.path, row['id'])['data']
        self.assertEqual(ops.attachment_content(self.path, meta['id'])['content'], b'<script>plain text only</script>')
        with self.assertRaises(APIError):
            service.save_record(self.path, example(serial_no='BAD-ATTACHMENT', attachment=upload(b'', 'bad.txt')))
        self.assertIsNone(service.serial_mapping(self.path, 'BAD-ATTACHMENT')['data'])
        ops.delete(self.path, 'records', row['id'], {'expected_version':1})
        with self.assertRaises(APIError):
            ops.attachment_content(self.path, meta['id'])

    def test_attachment_validation_and_concurrency(self):
        row = service.save_record(self.path, example())['data']
        bad = [upload(filename='../bad.txt'), upload(filename='bad.html'), {'filename':'x.txt','content_base64':'!'}, upload(b''), upload(b'x' * (5 * 1024 * 1024 + 1))]
        for attachment in bad:
            with self.subTest(filename=attachment['filename']), self.assertRaises(APIError):
                ops.upload_attachment(self.path, row['id'], dict(expected_version=1, attachment=attachment))
        def send(_):
            try:
                ops.upload_attachment(self.path, row['id'], dict(expected_version=1, attachment=upload()))
                return 200
            except APIError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(send, range(2))), [200,409])
        meta = ops.attachment_metadata(self.path, row['id'])['data']
        with self.assertRaises(APIError):
            ops.delete(self.path, 'attachments', meta['id'], {'expected_version':1})
        ops.delete(self.path, 'attachments', meta['id'], {'expected_version':2})
        self.assertIsNone(ops.attachment_metadata(self.path, row['id'])['data'])

    def test_pass_zero_amount_and_closed_edit(self):
        row = self.ready(repair_type='合約')
        result = ops.resolve(self.path, row['id'], dict(expected_version=2, passed=True))
        self.assertEqual(result['data']['current_status'], '結案（PASS）')
        self.assertEqual(result['data']['repair_amount'], 0)
        with self.assertRaises(APIError):
            ops.resolve(self.path, row['id'], dict(expected_version=2, passed=True))
        after = service.save_record(self.path, example(repair_type='合約', expected_version=3, current_status='結案（PASS）', sent_on='2026-11-02', returned_on='2026-11-02'), row['id'])['data']
        self.assertEqual(after['closed_on'], result['data']['closed_on'])

    def test_fail_retry_atomic_and_history(self):
        row = self.ready()
        result = ops.resolve(self.path, row['id'], dict(expected_version=2, passed=False, repair_type='保固', failure_description='第二輪', attachment=upload(b'new log')))
        child = result['retry']
        self.assertEqual(child['current_status'], '待送修')
        self.assertEqual(child['repair_amount'], 0)
        self.assertFalse(child['is_opened'])
        self.assertIsNone(child['sent_on'])
        self.assertEqual(child['retry_of_record_id'], row['id'])
        self.assertEqual(len(ops.chain(self.path, child['id'])['data']), 2)
        self.assertIsNone(ops.attachment_metadata(self.path, row['id'])['data'])
        self.assertEqual(ops.attachment_metadata(self.path, child['id'])['data']['file_size'], 7)
        with self.assertRaises(APIError):
            ops.delete(self.path, 'records', row['id'], {'expected_version':3})
        with self.assertRaises(APIError):
            ops.delete(self.path, 'records', child['id'], {'expected_version':1})

    def test_retry_failure_rolls_back_both_records(self):
        row = self.ready()
        for changes in ({'failure_description':''}, {'attachment':upload(filename='bad.exe')}, {'repair_type':'bad'}):
            with self.subTest(changes=changes), self.assertRaises(APIError):
                ops.resolve(self.path, row['id'], dict(expected_version=2, passed=False, repair_type='保固', failure_description='retry') | changes)
            self.assertEqual(service.record_detail(self.path, row['id'])['data']['version'], 2)
            self.assertEqual(service.list_records(self.path, {})['total'], 1)

    def test_resolve_requires_verified_priced_record(self):
        row = service.save_record(self.path, example())['data']
        with self.assertRaises(APIError):
            ops.resolve(self.path, row['id'], dict(expected_version=1, passed=True))
        unset = self.ready(serial_no='UNSET', description='ALPG', board_part_code='BIR-030349')
        with self.assertRaises(APIError):
            ops.resolve(self.path, unset['id'], dict(expected_version=2, passed=True))

    def test_simultaneous_resolve_one_winner(self):
        row = self.ready()
        def finish(_):
            try:
                ops.resolve(self.path, row['id'], dict(expected_version=2, passed=False, repair_type='保固', failure_description='retry'))
                return 200
            except APIError as error:
                return error.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(finish, range(2))), [200,409])
        self.assertEqual(service.list_records(self.path, {})['total'], 2)

    def mapping_values(self, **changes):
        return dict(previous_serial_no='002850948', serial_no='002850948', board_name='I/O PE', board_part_code='BIR-030083', **changes)

    def test_mapping_preview_only_and_explicit_sync(self):
        row = service.save_record(self.path, example())['data']
        dbn_row = ops.save_dbn(self.path, dbn())['data']
        values = self.mapping_values()
        impact = ops.preview_mapping(self.path, values)
        self.assertEqual((impact['repair_count'], impact['dbn_count']), (1,1))
        ops.save_mapping(self.path, dict(values, expected_version=1, sync_history=False, impact_token=impact['token']))
        self.assertEqual(service.record_detail(self.path, row['id'])['data']['description'], 'HVDR PE')
        ops.save_mapping(self.path, dict(values, expected_version=2, sync_history=True, impact_token=impact['token']))
        after = service.record_detail(self.path, row['id'])['data']
        self.assertEqual(after['description'], 'I/O PE')
        self.assertEqual(after['repair_amount'], row['repair_amount'])
        self.assertEqual(ops.list_dbn(self.path, {})['data'][0]['dut_pin_snapshot'], dbn_row['dut_pin_snapshot'])

    def test_mapping_stale_impact_rejected(self):
        service.save_record(self.path, example())
        values = self.mapping_values()
        impact = ops.preview_mapping(self.path, values)
        service.save_record(self.path, example())
        with self.assertRaises(APIError):
            ops.save_mapping(self.path, dict(values, expected_version=1, sync_history=True, impact_token=impact['token']))
        self.assertEqual(service.serial_mapping(self.path, '2850948')['data']['version'], 1)

    def test_rename_master_preserves_unsynced_history(self):
        row = service.save_record(self.path, example())['data']
        values = dict(self.mapping_values(), serial_no='RENAMED')
        impact = ops.preview_mapping(self.path, values)
        ops.save_mapping(self.path, dict(values, expected_version=1, sync_history=False, impact_token=impact['token']))
        self.assertEqual(service.record_detail(self.path, row['id'])['data']['serial_no'], '002850948')
        self.assertTrue(service.serial_mapping(self.path, '2850948')['data'])
        self.assertTrue(service.serial_mapping(self.path, 'RENAMED')['data'])
        with connect(self.path) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_rename_with_sync_and_conflict(self):
        row = service.save_record(self.path, example())['data']
        values = dict(self.mapping_values(), serial_no='RENAMED')
        impact = ops.preview_mapping(self.path, values)
        ops.save_mapping(self.path, dict(values, expected_version=1, sync_history=True, impact_token=impact['token']))
        self.assertEqual(service.record_detail(self.path, row['id'])['data']['serial_no'], 'RENAMED')
        self.assertIsNone(service.serial_mapping(self.path, '2850948')['data'])

    def test_master_prices_exact_and_no_history_reprice(self):
        row = service.save_record(self.path, example())['data']
        before = ops.masters(self.path)
        price = dict(model='T5377S', board_name='HVDR PE', board_part_code='BPR-030837', board_repair_cents=12345, external_repair_cents=None, contract_repair_cents=0, warranty_repair_cents=0)
        ops.save_master(self.path, dict(kind='price', value=price, expected_token=before['token']))
        self.assertEqual(service.record_detail(self.path, row['id'])['data']['repair_amount'], row['repair_amount'])
        self.assertEqual(service.save_record(self.path, example(serial_no='NEW'))['data']['repair_amount'], 123.45)
        with self.assertRaises(APIError):
            ops.save_master(self.path, dict(kind='price', value=price, expected_token=before['token']))

    def test_statistics_uses_root_damage_and_closed_round_amounts(self):
        row = self.ready(repair_type='合約')
        ops.resolve(self.path, row['id'], dict(expected_version=2, passed=False, repair_type='保固', failure_description='retry'))
        result = ops.statistics(self.path, {'mode':['year'],'period':['2026']})
        self.assertEqual(sum(result['frequency'].values()), 1)
        self.assertEqual(result['ranking'], [dict(machine='F45', count=1)])
        self.assertEqual(sum(sum(group.values()) for group in result['amounts_cents'].values()), 0)
        self.assertEqual(result['missing_amounts'], 0)
        with self.assertRaises(APIError):
            ops.statistics(self.path, {'mode':['month'],'period':['13']})

    def test_backup_recovers_attachments_and_does_not_overwrite(self):
        row = service.save_record(self.path, example(attachment=upload()))['data']
        output = self.path.parent / 'backup.sqlite3'
        counts = snapshot(self.path, output)
        self.assertEqual(counts['repair_attachments'], 1)
        with self.assertRaises(FileExistsError):
            snapshot(self.path, output)
        restored = self.path.parent / 'recovered.sqlite3'
        self.assertEqual(snapshot(output, restored), counts)
        self.assertEqual(verify(self.path), counts)
        meta = ops.attachment_metadata(restored, row['id'])['data']
        self.assertEqual(ops.attachment_content(restored, meta['id'])['content'], b'<script>plain text only</script>')

    def test_backup_detects_corrupted_attachment(self):
        service.save_record(self.path, example(attachment=upload()))
        with connect(self.path) as connection:
            connection.execute("UPDATE repair_attachments SET content=x'41'")
        output = self.path.parent / 'bad-backup.sqlite3'
        with self.assertRaises(ValueError):
            snapshot(self.path, output)
        self.assertFalse(output.exists())

    def test_sync_incompatible_model_rolls_back_master_and_records(self):
        row = service.save_record(self.path, example())['data']
        with connect(self.path) as connection:
            connection.execute("UPDATE repair_records SET model='HISTORICAL' WHERE id=?", (row['id'],))
        values = self.mapping_values()
        impact = ops.preview_mapping(self.path, values)
        with self.assertRaises(APIError):
            ops.save_mapping(self.path, dict(values, expected_version=1, sync_history=True, impact_token=impact['token']))
        self.assertEqual(service.serial_mapping(self.path, '2850948')['data']['board_name'], 'HVDR PE')
        self.assertEqual(service.record_detail(self.path, row['id'])['data']['version'], 1)


class FeatureUpgradeTests(unittest.TestCase):
    def test_v2_schema_conflict_rolls_back_added_columns_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'spms.sqlite3'
            with closing(sqlite3.connect(path)) as connection, connection:
                run_schema(connection, Path(__file__).resolve().parent / 'modules/repairs/schema.sql')
                connection.execute('CREATE TABLE spms_module_migrations(module TEXT,version INTEGER,applied_at TEXT,PRIMARY KEY(module,version))')
                connection.execute("INSERT INTO spms_module_migrations VALUES('repairs',1,'keep')")
                connection.execute('CREATE TABLE dbn_customers(user_work TEXT)')
                connection.execute("INSERT INTO dbn_customers VALUES('keep')")
            with self.assertRaises(sqlite3.OperationalError):
                initialize_database(path)
            with connect(path) as connection:
                self.assertNotIn('version', [row['name'] for row in connection.execute('PRAGMA table_info(serial_board_mappings)')])
                self.assertEqual(connection.execute('SELECT user_work FROM dbn_customers').fetchone()[0], 'keep')
                self.assertEqual([row[0] for row in connection.execute("SELECT version FROM spms_module_migrations WHERE module='repairs'")], [1])
            self.assertEqual(len(list((path.parent / 'backups').glob('*.sqlite3'))), 1)

    def test_v1_additive_upgrade_preserves_records_prices_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'spms.sqlite3'
            root = Path(__file__).resolve().parent
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('CREATE TABLE spms_schema_version(version INTEGER PRIMARY KEY,created_at TEXT)')
                connection.execute("INSERT INTO spms_schema_version VALUES(1,'original')")
                connection.execute('CREATE TABLE spms_module_migrations(module TEXT,version INTEGER,applied_at TEXT,PRIMARY KEY(module,version))')
                connection.execute("INSERT INTO spms_module_migrations VALUES('repairs',1,'original')")
                run_schema(connection, root / 'modules/repairs/schema.sql')
                catalog = json.loads((root / 'modules/repairs/catalog.json').read_text())
                connection.executemany('INSERT INTO repair_machine_models VALUES (:machine_code,:model)', catalog['machines'])
                connection.executemany('INSERT INTO repair_model_boards VALUES (:model,:board_name,:board_part_code)', catalog['boards'])
                connection.execute("INSERT INTO serial_board_mappings VALUES('OLD','HVDR PE','BPR-030837','old','old')")
                connection.execute("INSERT INTO repair_records(id,serial_no,machine_code,model,description,board_part_code,failure_tag,failure_description,repair_type,repair_amount_cents,current_status,is_opened,occurred_on,created_at,updated_at) VALUES('old','OLD','F45','T5377S','HVDR PE','BPR-030837','RTE','keep','板修',12345,'待送修',0,'2026-11-02','old','old')")
            initialize_database(path)
            backups = list((path.parent / 'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(service.record_detail(path, 'old')['data']['repair_amount'], 123.45)
            self.assertEqual(service.serial_mapping(path, 'OLD')['data']['version'], 1)
            with connect(backups[0]) as connection:
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='dbn_records'").fetchone())
            initialize_database(path)
            self.assertEqual(len(list((path.parent / 'backups').glob('*.sqlite3'))), 1)


class FeatureHTTPTests(unittest.TestCase):
    setUp = basic.RepairHTTPTests.setUp
    request = basic.RepairHTTPTests.request

    def test_dbn_mapping_history_and_stats_routes(self):
        self.assertEqual(len(self.request('/api/repairs/dbn/catalog')[1]['sockets']), 4)
        status, result = self.request('/api/repairs/dbn', 'POST', dbn())
        self.assertEqual(status, 201)
        identity = result['data']['id']
        self.request('/api/repairs/dbn/' + identity, 'PUT', dict(dbn(), expected_version=1))
        self.assertEqual(self.request('/api/repairs/dbn?serial=2850948')[1]['total'], 1)
        self.assertEqual(self.request('/api/repairs/mappings')[1]['total'], 1)
        self.assertEqual(self.request('/api/repairs/serial-summary?serial=2850948')[1]['models'], ['T5377S'])
        self.assertGreater(self.request('/api/repairs/history')[1]['total'], 1)
        self.request('/api/repairs/statistics?mode=year&period=2026')
        self.request('/api/repairs/masters')
        self.request('/api/repairs/dbn/' + identity, 'DELETE', {'expected_version':2})

    def test_attachment_bytes_head_and_headers(self):
        _, result = self.request('/api/repairs/records', 'POST', example(attachment=upload(filename='中文.asc')))
        identity = result['data']['id']
        _, meta = self.request('/api/repairs/records/' + identity + '/attachment')
        url = self.base + '/api/repairs/attachments/' + meta['data']['id']
        with urlopen(url + '?download=1') as response:
            self.assertEqual(response.read(), b'<script>plain text only</script>')
            self.assertTrue(response.headers['Content-Disposition'].startswith('attachment;'))
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(response.headers.get_content_type(), 'text/plain')
        with urlopen(Request(url, method='HEAD')) as response:
            self.assertEqual(response.read(), b'')
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/repairs/attachments/' + meta['data']['id'], 'DELETE', {'expected_version':1}, {'Origin':'http://evil.example'})
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()
