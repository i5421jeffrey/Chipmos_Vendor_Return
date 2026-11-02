import csv
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import legacy_import as legacy
from database import connect
from errors import APIError
from maintenance import snapshot, verify
from modules.repairs import operations as ops, service
from server import initialize_database
from test_repairs import example


def fixture():
    tables = {name: [] for name in legacy.TABLES}
    repair = example()
    repair.update(id='source-repair', model='T5377S', version='7', repair_amount='123.45',
                  closed_on='', retry_of_record_id='', created_at='2026-10-01 01:00:00+00', updated_at='2026-10-02 02:00:00+00',
                  legacy_extra='retain me', is_opened='true')
    repair['sent_on'] = repair.get('sent_on') or ''
    repair['returned_on'] = repair.get('returned_on') or ''
    tables['repair_records'] = [repair]
    tables['serial_board_mappings'] = [dict(serial_no=repair['serial_no'],board_name=repair['description'],board_part_code=repair['board_part_code'],updated_at='2026-10-02T00:00:00Z')]
    tables['dbn_records'] = [dict(id='source-dbn', serial_no=repair['serial_no'], machine_code='F45',model='T5377S',board_name=repair['description'],board_part_code=repair['board_part_code'],customer_code='AB',product_code='JAA118',station_code='CP1',issue_type='',dut='',issue_description='',socket_file_id='',dut_pin_snapshot='{}',created_at='2026-10-02 00:00:00+00')]
    content = b'original bytes\r\n<not html>'
    tables['repair_attachments'] = [dict(id='source-attachment',repair_record_id='source-repair',storage_path='source-repair/file.asc',filename='same-name.asc',file_size=str(len(content)),content_type='text/plain',created_at='2026-10-02T00:00:00Z')]
    tables['record_change_history'] = [dict(id='1',changed_at='2026-10-02 01:00:00+00',source_table='repair_records',record_key='deleted-old-record',operation='DELETE',serial_no=repair['serial_no'],board_name=repair['description'],changes=json.dumps({'failure_description':{'old':'source','new':None}}),search_text='original search',dbn_before='',dbn_after='')]
    return tables, content


def bundle(tables, content):
    files = {}
    for table, rows in tables.items():
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]) if rows else ['id'])
        writer.writeheader()
        writer.writerows(rows)
        files[table] = legacy.encoded(buffer.getvalue().encode('utf-8-sig'))
    return dict(format=legacy.FORMAT, source_description='synthetic fixture, not company data', source_files=files,
                attachments={'source-repair/file.asc':legacy.encoded(content)})


class LegacyImportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'spms.sqlite3'
        initialize_database(self.path)
        self.tables, self.content = fixture()

    def package(self):
        return bundle(self.tables, self.content)

    def test_preview_unchanged_apply_preserves_source_and_business_snapshots(self):
        package = self.package()
        preview = legacy.check(self.path, package)
        self.assertEqual(preview['incomplete_dbn'], 1)
        self.assertEqual(service.list_records(self.path,{})['total'], 0)
        applied = legacy.apply(self.path, package)
        self.assertTrue(Path(applied['backup']).is_file())
        record = service.record_detail(self.path,'source-repair')['data']
        self.assertEqual(record['repair_amount'],123.45)
        self.assertEqual(record['version'],7)
        self.assertEqual(record['created_at'],self.tables['repair_records'][0]['created_at'])
        self.assertEqual(record['legacy_source']['legacy_extra'],'retain me')
        self.assertEqual(ops.list_dbn(self.path,{})['total'],1)
        self.assertIsNone(ops.list_dbn(self.path,{})['data'][0]['issue_type'])
        with connect(self.path) as c:
            saved = c.execute("SELECT * FROM repair_attachments WHERE id='source-attachment'").fetchone()
            self.assertEqual(saved['content'], self.content)
            self.assertEqual(c.execute('SELECT count(*) FROM legacy_source_files').fetchone()[0],13)
            self.assertEqual(c.execute("SELECT record_id FROM record_change_history WHERE id LIKE 'legacy-%'").fetchone()[0],'deleted-old-record')
        self.assertEqual(verify(self.path)['dbn_records'],1)
        filtered=ops.history(self.path,{'start':['2026-10-02'],'end':['2026-10-02'],'operation':['DELETE']})
        self.assertEqual(filtered['total'],1)
        self.assertTrue(filtered['data'][0]['id'].startswith('legacy-'))
        with self.assertRaises((ValueError,sqlite3.IntegrityError)):
            legacy.apply(self.path, package)
        self.assertEqual(verify(self.path)['repair_records'],1)

    def test_date_anomaly_preserved_but_resolution_blocked(self):
        row = self.tables['repair_records'][0]
        row.update(current_status='取回驗證',occurred_on='2026-09-01',sent_on='2026-09-20',returned_on='2026-09-10')
        legacy.apply(self.path,self.package())
        record = service.record_detail(self.path,'source-repair')['data']
        self.assertTrue(record['legacy_warnings'])
        self.assertEqual(record['returned_on'],'2026-09-10')
        with self.assertRaises(APIError):
            ops.resolve(self.path,'source-repair',dict(expected_version=7,passed=True))
        self.assertEqual(service.record_detail(self.path,'source-repair')['data']['current_status'],'取回驗證')

    def test_legacy_dbn_requires_explicit_type_then_promotes_and_keeps_original(self):
        legacy.apply(self.path,self.package())
        row = self.tables['dbn_records'][0]
        payload = {k:row[k] for k in ('serial_no','machine_code','board_name','board_part_code','customer_code','product_code','station_code','issue_type','dut','issue_description')}
        with self.assertRaises(APIError):
            ops.save_dbn(self.path,dict(payload,expected_version=1),'source-dbn')
        saved = ops.save_dbn(self.path,dict(payload,issue_type='RTE',issue_description='explicit reviewed description',expected_version=1),'source-dbn')['data']
        self.assertEqual(saved['version'],2)
        self.assertEqual(saved['id'],'source-dbn')
        self.assertEqual(ops.list_dbn(self.path,{})['data'][0]['legacy_incomplete'],0)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM legacy_dbn_records').fetchone()[0],0)
            raw=c.execute("SELECT original_json FROM legacy_source_rows WHERE source_table='dbn_records'").fetchone()[0]
            self.assertEqual(json.loads(raw)['issue_type'],'')

    def test_pin_snapshot_not_recomputed_and_mapping_preview_covers_legacy(self):
        self.tables['dbn_records'].append(dict(self.tables['dbn_records'][0],id='typed-dbn',issue_type='Group',dut='1-2',dut_pin_snapshot=json.dumps({'1':['HISTORICAL'],'2':None})))
        legacy.apply(self.path,self.package())
        result=ops.list_dbn(self.path,{})
        self.assertEqual(result['total'],2)
        self.assertEqual(next(x for x in result['data'] if x['id']=='typed-dbn')['dut_pin_snapshot'],{'1':['HISTORICAL'],'2':None})
        mapping=self.tables['serial_board_mappings'][0]
        impact=ops.preview_mapping(self.path,dict(serial_no=mapping['serial_no'],board_name=mapping['board_name'],board_part_code='new-part'))
        self.assertEqual(impact['dbn_count'],2)

    def test_corrupt_missing_attachments_and_conflicts_rollback_everything(self):
        package=self.package()
        package['attachments']['source-repair/file.asc']['sha256']='0'*64
        with self.assertRaises(ValueError): legacy.apply(self.path,package)
        self.assertEqual(verify(self.path)['repair_records'],0)
        self.assertEqual(ops.list_mappings(self.path,{})['total'],0)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM legacy_import_batches').fetchone()[0],0)
        package=self.package(); package['attachments'].clear()
        with self.assertRaises(ValueError): legacy.check(self.path,package)
        self.tables['repair_machine_models']=[dict(machine_code='F45',model='CONFLICT')]
        with self.assertRaises(ValueError): legacy.apply(self.path,self.package())
        self.assertEqual(verify(self.path)['repair_records'],0)

    def test_source_archive_integrity_and_backup_includes_legacy(self):
        legacy.apply(self.path,self.package())
        target=self.path.with_name('backup.sqlite3')
        snapshot(self.path,target)
        self.assertEqual(verify(target)['dbn_records'],1)
        with connect(target) as c:
            c.execute("UPDATE legacy_source_files SET content=X'00' WHERE filename='repair_records_rows.csv'")
        with self.assertRaises(ValueError): verify(target)

    def test_same_original_filename_different_cases_remains_separate(self):
        other=dict(self.tables['repair_records'][0],id='source-other')
        self.tables['repair_records'].append(other)
        self.tables['repair_attachments'].append(dict(self.tables['repair_attachments'][0],id='other-attachment',repair_record_id='source-other',storage_path='source-other/file.asc',file_size='5'))
        package=self.package(); package['attachments']['source-other/file.asc']=legacy.encoded(b'other')
        legacy.apply(self.path,package)
        with connect(self.path) as c:
            rows=c.execute('SELECT filename,content FROM repair_attachments').fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual({r['content'] for r in rows},{self.content,b'other'})

    def test_source_retry_chronology_is_flagged_without_rewriting(self):
        parent=self.tables['repair_records'][0]
        parent.update(current_status='結案（FAIL）',occurred_on='2026-05-01',sent_on='2026-05-02',returned_on='2026-05-03',closed_on='2026-10-01')
        retry=dict(parent,id='source-retry',current_status='待送修',occurred_on='2026-07-01',sent_on='',returned_on='',closed_on='',retry_of_record_id=parent['id'])
        self.tables['repair_records'].append(retry)
        result=legacy.apply(self.path,self.package())
        self.assertEqual(result['operational_repairs'],2)
        record=service.record_detail(self.path,'source-retry')['data']
        self.assertEqual(record['occurred_on'],'2026-07-01')
        self.assertTrue(any('前輪結案' in warning for warning in record['legacy_warnings']))
        self.assertEqual(len(ops.chain(self.path,'source-retry')['data']),2)

    def test_postgres_short_offset_sorts_by_instant_and_null_zero_amounts_stay_distinct(self):
        self.tables['repair_records'][0].update(repair_amount='',created_at='2026-10-01 10:00:00+08')
        self.tables['repair_records'].append(dict(self.tables['repair_records'][0],id='later',repair_amount='0.00',created_at='2026-10-01 03:00:00+00'))
        legacy.apply(self.path,self.package())
        records=service.list_records(self.path,{})['data']
        self.assertEqual(records[0]['id'],'later')
        self.assertEqual(records[0]['repair_amount'],0)
        self.assertIsNone(records[1]['repair_amount'])

    def test_cli_preview_and_cancel_never_import(self):
        path=self.path.parent / 'source_bundle.json'
        path.write_text(json.dumps(self.package()),encoding='utf-8')
        script=Path(legacy.__file__)
        for flags, answer, expected in (([], '', 'CHECK ONLY'),(['--apply'],'NO\n','Cancelled')):
            completed=subprocess.run([sys.executable,str(script),'import',str(path),'--database',str(self.path),*flags],input=answer,text=True,capture_output=True,timeout=20)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            self.assertIn(expected,completed.stdout)
            self.assertEqual(verify(self.path)['repair_records'],0)

    def test_additive_upgrade_from_existing_v2_keeps_business_data(self):
        # Temporary test fixture only: simulate an installation predating the archive module.
        service.save_record(self.path,example())
        with connect(self.path) as c:
            c.execute('DROP VIEW all_dbn_records')
            for table in ('legacy_dbn_records','legacy_source_rows','legacy_source_files','legacy_import_batches'):
                c.execute('DROP TABLE '+table)
            c.execute("DELETE FROM spms_module_migrations WHERE module='legacy_import'")
        initialize_database(self.path)
        self.assertEqual(service.list_records(self.path,{})['total'],1)
        backups=list((self.path.parent/'backups').glob('*.sqlite3'))
        self.assertEqual(len(backups),1)
        self.assertEqual(verify(backups[0])['repair_records'],1)
        initialize_database(self.path)
        self.assertEqual(len(list((self.path.parent/'backups').glob('*.sqlite3'))),1)


if __name__ == '__main__':
    unittest.main()
