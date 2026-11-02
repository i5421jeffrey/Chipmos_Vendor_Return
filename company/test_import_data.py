import json
import sqlite3
import unittest

import import_data
import test_features as features
from database import connect
from errors import APIError
from modules.repairs import operations as ops, service
from test_repairs import example


def package(**changes):
    return dict(format='spms-offline-import-v1', source_description='offline test fixture', **changes)


class ImportTests(unittest.TestCase):
    setUp = features.FeatureTests.setUp

    def test_check_never_modifies_source_and_apply_preserves_exact_price(self):
        data = package(repair_records=[example(id='source-id', repair_amount='123.45', created_at='2020-01-01T00:00:00+08:00')],
                       repair_attachments=[dict(repair_record_id='source-id', **features.upload())])
        data = import_data.package_from_bytes(json.dumps(data).encode())
        result = import_data.check(self.path, data)
        self.assertEqual(result['repair_records'], 1)
        self.assertEqual(service.list_records(self.path, {})['total'], 0)
        applied = import_data.apply(self.path, data)
        self.assertIn('before-import-', applied['backup'])
        row = service.record_detail(self.path, 'source-id')['data']
        self.assertEqual(row['repair_amount'], 123.45)
        self.assertEqual(row['created_at'], '2020-01-01T00:00:00+08:00')
        self.assertTrue(ops.attachment_metadata(self.path, row['id'])['data'])
        with self.assertRaises(sqlite3.IntegrityError):
            import_data.apply(self.path, data)
        self.assertEqual(service.list_records(self.path, {})['total'], 1)

    def test_any_invalid_record_rolls_back_batch_and_master(self):
        data = package(repair_records=[example(id='valid', serial_no='VALID', repair_amount=0), example(id='bad', serial_no='BAD', repair_amount='NaN')])
        with self.assertRaises(APIError):
            import_data.apply(self.path, data)
        self.assertEqual(service.list_records(self.path, {})['total'], 0)
        self.assertIsNone(service.serial_mapping(self.path, 'VALID')['data'])

    def test_import_dbn_preserves_explicit_snapshot(self):
        data = package(dbn_records=[dict(features.dbn(), id='dbn-old', dut_pin_snapshot={str(number):['HISTORICAL-PIN'] for number in range(1,5)}, socket_file_id='old-socket-id')])
        import_data.apply(self.path, data)
        row = ops.list_dbn(self.path, {})['data'][0]
        self.assertEqual(row['dut_pin_snapshot']['1'], ['HISTORICAL-PIN'])
        self.assertEqual(row['socket_file_id'], 'old-socket-id')
        without_snapshot = package(dbn_records=[dict(features.dbn(), id='dbn-bad')])
        with self.assertRaises(APIError):
            import_data.check(self.path, without_snapshot)

    def test_import_chain_out_of_order_and_cycle_rejection(self):
        root = example(id='root', current_status='結案（FAIL）', sent_on='2026-11-02', returned_on='2026-11-02', closed_on='2026-11-02', repair_amount=0)
        child = example(id='child', repair_amount=None, retry_of_record_id='root')
        import_data.apply(self.path, package(repair_records=[child, root]))
        self.assertEqual(len(ops.chain(self.path, 'child')['data']), 2)
        cyclic = package(repair_records=[dict(root, id='cycle', retry_of_record_id='cycle')])
        with self.assertRaises(APIError):
            import_data.check(self.path, cyclic)

    def test_duplicate_master_conflict_and_nonempty_import(self):
        service.save_record(self.path, example(serial_no='EXISTING'))
        valid = package(repair_records=[example(id='another', serial_no='NEW', repair_amount=0)])
        import_data.apply(self.path, valid)
        self.assertEqual(service.list_records(self.path, {})['total'], 2)
        conflict = package(serial_board_mappings=[dict(serial_no='EXISTING', board_name='I/O PE', board_part_code='BIR-030083')])
        with self.assertRaises(APIError):
            import_data.apply(self.path, conflict)
        self.assertEqual(service.serial_mapping(self.path, 'EXISTING')['data']['board_name'], 'HVDR PE')

    def test_unreviewed_format_money_and_date_rejected(self):
        for value in ([], {}, {'format':'sql'}, package(unexpected=[])):
            with self.assertRaises(ValueError):
                import_data.package_from_bytes(json.dumps(value).encode())
        for amount in (True, '0.001', -1, 'Infinity'):
            with self.assertRaises(APIError):
                import_data.amount_cents(amount)
        self.assertEqual(import_data.amount_cents('0'), 0)
        self.assertIsNone(import_data.amount_cents(None))
        for value in ('2026-02-30', None, '20261102'):
            with self.assertRaises(APIError):
                import_data.iso_date(value)


if __name__ == '__main__':
    unittest.main()
