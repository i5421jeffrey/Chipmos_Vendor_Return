"""Read-only CSV conversion and backed-up import of a complete reviewed source bundle.

No network, SQL dump execution, conflict overwrite, date repair or PIN recalculation.
Source CSV bytes and every original field are archived inside SQLite in the same transaction.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

import import_data as reviewed
from database import connect, utc_now
from errors import APIError
from maintenance import snapshot, verify
from modules.repairs import attachments, operations as ops, service

TABLES = ('dbn_customers', 'dbn_records', 'dbn_socket_files', 'dbn_valid_combinations',
          'record_change_history', 'repair_attachments', 'repair_board_prices',
          'repair_machine_models', 'repair_machines', 'repair_model_boards',
          'repair_models', 'repair_records', 'serial_board_mappings')
FORMAT = 'spms-legacy-csv-v1'


def encoded(raw):
    return dict(content_base64=base64.b64encode(raw).decode('ascii'), sha256=hashlib.sha256(raw).hexdigest())


def decoded(item):
    try:
        raw = base64.b64decode(item['content_base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Source checksum mismatch')
        return raw
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid source bytes or SHA256') from error


def parse_csv(raw):
    csv.field_size_limit(64 * 1024 * 1024)
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
    columns = reader.fieldnames
    if not columns or len(set(columns)) != len(columns) or any(not name for name in columns):
        raise ValueError('Missing or duplicate CSV column names')
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError('Malformed CSV row')
    return rows


def source_data(package):
    if not isinstance(package, dict) or package.get('format') != FORMAT or set(package) != {'format', 'source_description', 'source_files', 'attachments'}:
        raise ValueError('Expected spms-legacy-csv-v1 bundle')
    ops.text(package['source_description'], 'source_description', 2000)
    if not isinstance(package['source_files'], dict) or set(package['source_files']) != set(TABLES):
        raise ValueError('All 13 reviewed CSV tables are required')
    data = {table: parse_csv(decoded(package['source_files'][table])) for table in TABLES}
    if not isinstance(package['attachments'], dict):
        raise ValueError('Invalid attachments map')
    expected = {row['storage_path'] for row in data['repair_attachments']}
    if set(package['attachments']) != expected or len(expected) != len(data['repair_attachments']):
        raise ValueError('Missing, duplicate or unexpected attachment paths')
    for name in expected:
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name:
            raise ValueError('Unsafe attachment path')
    return data


def build(csv_directory, files_directory, description):
    package = dict(format=FORMAT, source_description=description, source_files={}, attachments={})
    for table in TABLES:
        package['source_files'][table] = encoded((Path(csv_directory) / (table + '_rows.csv')).read_bytes())
    data = {table: parse_csv(decoded(item)) for table, item in package['source_files'].items()}
    root = Path(files_directory).resolve()
    for row in data['repair_attachments']:
        name = row['storage_path']
        parts = PurePosixPath(name)
        if parts.is_absolute() or '..' in parts.parts or '\\' in name:
            raise ValueError('Unsafe attachment path')
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Attachment escapes selected folder')
        package['attachments'][name] = encoded(path.read_bytes())
    source_data(package)
    return package


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > 100 * 1024 * 1024:
        raise ValueError('Bundle exceeds 100 MB')
    value = json.loads(raw)
    source_data(value)
    return value


def integer(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError(label + ' must be a positive integer')
    return int(value)


def boolean(value):
    if value not in ('true', 'false'):
        raise ValueError('Expected source true/false')
    return value == 'true'


def nullable(value):
    return None if value == '' else value


def same_or_insert(connection, table, values, keys):
    where = ' AND '.join(key + '=?' for key in keys)
    previous = connection.execute('SELECT * FROM ' + table + ' WHERE ' + where, [values[key] for key in keys]).fetchone()
    if previous:
        if any(previous[key] != value for key, value in values.items()):
            raise ValueError('Existing catalog conflict in ' + table + '; no overwrite performed')
    else:
        reviewed.insert(connection, table, values)


def archive_row(connection, batch, table, key, row, warnings=()):
    reviewed.insert(connection, 'legacy_source_rows', dict(source_table=table, source_key=key, batch_id=batch,
                    original_json=json.dumps(row, ensure_ascii=False), warnings=json.dumps(list(warnings), ensure_ascii=False)))


def date_warnings(row):
    issues = []
    if row['sent_on'] and row['sent_on'] < row['occurred_on']:
        issues.append('來源送修日期早於損壞日期；原樣保留，須核對後才能結案')
    if row['returned_on'] and (not row['sent_on'] or row['returned_on'] < row['sent_on']):
        issues.append('來源回修日期早於送修日期或缺送修日期；原樣保留，須核對後才能結案')
    if row['closed_on'] and row['closed_on'] < row['returned_on']:
        issues.append('來源結案日期早於回修日期；原樣保留，須核對')
    return issues


def import_into(connection, package):
    data = source_data(package)
    connection.execute('PRAGMA defer_foreign_keys=ON')
    batch = uuid4().hex
    now = utc_now()
    reviewed.insert(connection, 'legacy_import_batches', dict(id=batch, imported_at=now, source_description=package['source_description']))
    for table, item in package['source_files'].items():
        reviewed.insert(connection, 'legacy_source_files', dict(batch_id=batch, filename=table + '_rows.csv', sha256=item['sha256'], content=decoded(item)))
    for table, keys in (('repair_machine_models', ('machine_code',)), ('repair_model_boards', ('model', 'board_name')),
                        ('dbn_customers', ('customer_code',)), ('dbn_valid_combinations', ('customer_code', 'product_code', 'station_code'))):
        columns = [row['name'] for row in connection.execute('PRAGMA table_info(' + table + ')')]
        for row in data[table]:
            values = {key: ops.text(row[key], key) for key in columns}
            same_or_insert(connection, table, values, keys)
    for row in data['repair_board_prices']:
        values = {key: row[key] for key in ('model', 'board_name', 'board_part_code')}
        for prefix in ('board_repair', 'external_repair', 'contract_repair', 'warranty_repair'):
            values[prefix + '_cents'] = reviewed.amount_cents(nullable(row[prefix + '_amount']))
        same_or_insert(connection, 'repair_board_prices', values, ('model', 'board_name', 'board_part_code'))
    for row in data['dbn_socket_files']:
        if not boolean(row['is_active']):
            raise ValueError('Inactive Socket requires explicit review; archived source is not auto-selected')
        pins = json.loads(row['dut_pins'])
        count = integer(row['dut_count'], 'dut_count')
        if not isinstance(pins, dict) or any(not isinstance(v, list) or any(not isinstance(p, str) for p in v) for v in pins.values()):
            raise ValueError('Invalid source socket pins')
        values = dict(id=reviewed.identity(row['id']), product_code=row['product_code'], source_filename=row['source_filename'], dut_count=count,
                      dut_pins=json.dumps(pins, ensure_ascii=False))
        existing = connection.execute('SELECT * FROM dbn_socket_files WHERE product_code=?', (row['product_code'],)).fetchone()
        if existing:
            if any(existing[k] != values[k] for k in ('id','product_code','source_filename','dut_count')) or json.loads(existing['dut_pins']) != pins:
                raise ValueError('Existing Socket conflict; no overwrite performed')
        else:
            reviewed.insert(connection, 'dbn_socket_files', values)
    for row in data['serial_board_mappings']:
        number = ops.serial(row['serial_no'])
        if number != row['serial_no']:
            raise ValueError('Source S/N requires explicit normalization review')
        existed = connection.execute('SELECT 1 FROM serial_board_mappings WHERE serial_no=?', (number,)).fetchone()
        ops.ensure_mapping(connection, row)
        # A source mapping has no created_at/version. Preserve its updated_at;
        # newly imported local created_at uses that known source timestamp.
        stamp = reviewed.timestamp(row['updated_at'], None)
        if stamp is None:
            raise ValueError('Source mapping updated_at missing')
        previous = connection.execute("SELECT 1 FROM legacy_source_rows WHERE source_table='serial_board_mappings' AND source_key=?", (number,)).fetchone()
        if previous:
            raise ValueError('Source mapping already imported')
        if not existed:
            connection.execute('UPDATE serial_board_mappings SET created_at=?,updated_at=? WHERE serial_no=?', (stamp, stamp, number))
        archive_row(connection, batch, 'serial_board_mappings', number, row)
    warning_rows = []
    source_repairs = {row['id']: row for row in data['repair_records']}
    for row in data['repair_records']:
        fields = {key: nullable(row[key]) if key in ('sent_on', 'returned_on') else row[key] for key in service.FIELDS}
        fields['is_opened'] = boolean(row['is_opened'])
        closed = row['current_status'] in ('結案（PASS）', '結案（FAIL）')
        if closed:
            fields['current_status'] = '取回驗證'
        values = service.validate(connection, fields, historical=True)
        if values['serial_no'] != row['serial_no'] or values['model'] != row['model']:
            raise ValueError('Source repair S/N or Model differs from current source context')
        values.update(id=reviewed.identity(row['id']), current_status=row['current_status'],
                      repair_amount_cents=reviewed.amount_cents(nullable(row['repair_amount'])),
                      closed_on=reviewed.iso_date(row['closed_on']) if closed else None,
                      retry_of_record_id=reviewed.identity(row['retry_of_record_id']) if row['retry_of_record_id'] else None,
                      version=integer(row['version'], 'version'), created_at=reviewed.timestamp(row['created_at'], None), updated_at=reviewed.timestamp(row['updated_at'], None))
        if not values['created_at'] or not values['updated_at'] or (not closed and row['closed_on']):
            raise ValueError('Missing source timestamps or unexpected closure date')
        if values['repair_type'] == '保固' and values['repair_amount_cents'] not in (0, None):
            raise ValueError('Nonzero warranty amount')
        ops.ensure_mapping(connection, {**values, 'board_name': values['description']})
        reviewed.insert(connection, 'repair_records', values)
        warnings = date_warnings(row)
        if row['retry_of_record_id']:
            parent = source_repairs.get(row['retry_of_record_id'])
            if parent and parent['closed_on'] > row['occurred_on']:
                warnings.append('來源再次送修損壞日早於前輪結案日；原關聯與日期保留，未推測實際時間')
        archive_row(connection, batch, 'repair_records', row['id'], row, warnings)
        if warnings:
            warning_rows.append(dict(table='repair_records', id=row['id'], warnings=warnings))
        service.audit(connection, 'repair_records', row['id'], 'IMPORT', None, service.public_record(ops.get_row(connection, 'repair_records', row['id'])))
    for row in data['repair_records']:
        current, seen = row, set()
        while current['retry_of_record_id']:
            if current['id'] in seen:
                raise ValueError('Retry cycle')
            seen.add(current['id'])
            parent = dict(ops.get_row(connection, 'repair_records', current['retry_of_record_id']))
            if parent['current_status'] != '結案（FAIL）' or parent['serial_no'] != current['serial_no'] or not parent['closed_on']:
                raise ValueError('Invalid source retry relationship')
            current = parent
    for row in data['dbn_records']:
        if connection.execute('SELECT 1 FROM all_dbn_records WHERE id=?', (row['id'],)).fetchone():
            raise ValueError('Existing DBN ID conflict')
        values = {key: row[key] for key in ('serial_no','machine_code','model','board_name','board_part_code','customer_code')}
        if ops.serial(values['serial_no']) != values['serial_no'] or ops.board_context(connection, values['machine_code'], values['board_name'], values['board_part_code']) != values['model']:
            raise ValueError('DBN source context mismatch')
        values.update({key: nullable(row[key]) for key in ('product_code','station_code')})
        snapshot_pins = json.loads(row['dut_pin_snapshot'])
        incomplete = not row['issue_type']
        if incomplete:
            if row['dut'] or row['socket_file_id'] or snapshot_pins or row['issue_description']:
                raise ValueError('Untyped DBN has issue information; requires explicit review')
            issue = dict(issue_type=None, dut=None, issue_description=None, socket_file_id=None, dut_pin_snapshot='{}')
        else:
            issue = ops.validate_issue(row)
            if issue['dut'] != nullable(row['dut']):
                raise ValueError('Source DUT requires explicit canonical-format review')
            if row['issue_type'] in ('RTE','Other') and (row['dut'] or row['socket_file_id'] or snapshot_pins):
                raise ValueError('RTE/Other source unexpectedly contains DUT/PIN information')
            if row['issue_type'] in ('Group','Single Dut') and row['issue_description']:
                raise ValueError('DUT source unexpectedly contains an extra description; requires review')
            issue['issue_description'] = nullable(row['issue_description'])
            if not isinstance(snapshot_pins, dict) or set(snapshot_pins) != set(json.loads(issue['dut_pin_snapshot'])):
                raise ValueError('Source PIN snapshot does not match DUT selection')
            for pins in snapshot_pins.values():
                if pins is not None and (not isinstance(pins, list) or any(not isinstance(pin, str) or not 1 <= len(pin) <= 200 for pin in pins)):
                    raise ValueError('Invalid source PIN token')
            issue.update(dut_pin_snapshot=json.dumps(snapshot_pins, ensure_ascii=False), socket_file_id=nullable(row['socket_file_id']))
            if issue['socket_file_id'] and not connection.execute('SELECT 1 FROM dbn_socket_files WHERE id=? AND product_code=?', (issue['socket_file_id'],values['product_code'])).fetchone():
                raise ValueError('Source Socket reference mismatch')
        stamp = reviewed.timestamp(row['created_at'], None)
        if not stamp:
            raise ValueError('Missing source DBN created_at')
        values.update(issue, id=reviewed.identity(row['id']), created_at=stamp, updated_at=stamp, version=1)
        ops.ensure_mapping(connection, values)
        reviewed.insert(connection, 'legacy_dbn_records' if incomplete else 'dbn_records', values)
        warnings = ['舊 DBN 未記錄類型；未猜測類型或 PIN。編輯時須明確補齊。'] if incomplete else []
        archive_row(connection, batch, 'dbn_records', row['id'], row, warnings)
        if warnings:
            warning_rows.append(dict(table='dbn_records', id=row['id'], warnings=warnings))
        service.audit(connection, 'dbn_records', row['id'], 'IMPORT', None, ops.public_dbn(ops.get_row(connection, 'dbn_records', row['id'])))
    attachment_hashes = {}
    for row in data['repair_attachments']:
        content = decoded(package['attachments'][row['storage_path']])
        if len(content) != integer(row['file_size'], 'file_size'):
            raise ValueError('Source attachment size mismatch')
        upload = dict(filename=row['filename'], content_base64=base64.b64encode(content).decode('ascii'))
        attachments.decode_upload(upload)
        reviewed.insert(connection, 'repair_attachments', dict(id=reviewed.identity(row['id']), repair_record_id=row['repair_record_id'], filename=row['filename'],
                        content=content, sha256=hashlib.sha256(content).hexdigest(), created_at=reviewed.timestamp(row['created_at'], None)))
        archive_row(connection, batch, 'repair_attachments', row['id'], row)
        attachment_hashes[row['id']] = hashlib.sha256(content).hexdigest()
    for row in data['record_change_history']:
        changes = json.loads(row['changes'])
        if not isinstance(changes, dict) or any(not isinstance(v, dict) or set(v) - {'old','new'} for v in changes.values()):
            raise ValueError('Invalid source history changes')
        if row['source_table'] not in ('repair_records','dbn_records','serial_board_mappings','repair_machine_models','repair_model_boards','repair_board_prices','repair_attachments') or row['operation'] not in ('INSERT','UPDATE','DELETE'):
            raise ValueError('Unreviewed source history type')
        # Prefix makes imported source history distinct from locally generated IMPORT events.
        reviewed.insert(connection, 'record_change_history', dict(id='legacy-' + batch[:12] + '-' + reviewed.identity(row['id']),
                        source_table=row['source_table'], record_id=row['record_key'], operation=row['operation'], serial_no=nullable(row['serial_no']), board_name=nullable(row['board_name']),
                        changed_at=reviewed.timestamp(row['changed_at'], None), changes=json.dumps(changes, ensure_ascii=False)))
        archive_row(connection, batch, 'record_change_history', row['id'], row)
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Imported foreign key check failed')
    # Reconcile business snapshots, not merely totals or the converter's inputs.
    for row in data['repair_records']:
        saved = dict(ops.get_row(connection, 'repair_records', row['id']))
        for key in service.FIELDS - {'is_opened','sent_on','returned_on'}:
            if saved[key] != row[key]:
                raise ValueError('Repair field reconciliation failed: ' + key)
        for key in ('sent_on','returned_on','closed_on','retry_of_record_id'):
            if saved[key] != nullable(row[key]):
                raise ValueError('Repair date/chain reconciliation failed')
        if saved['repair_amount_cents'] != reviewed.amount_cents(nullable(row['repair_amount'])) or saved['version'] != int(row['version']) or bool(saved['is_opened']) != boolean(row['is_opened']):
            raise ValueError('Repair amount/version reconciliation failed')
        if any(saved[key] != row[key] for key in ('model','created_at','updated_at')):
            raise ValueError('Repair source time/Model reconciliation failed')
    for row in data['dbn_records']:
        saved = dict(ops.get_row(connection, 'dbn_records', row['id']))
        if json.loads(saved['dut_pin_snapshot']) != json.loads(row['dut_pin_snapshot']):
            raise ValueError('PIN reconciliation failed')
        for key in ('serial_no','machine_code','model','board_name','board_part_code','customer_code','created_at'):
            if saved[key] != row[key]:
                raise ValueError('DBN field reconciliation failed: ' + key)
        for key in ('product_code','station_code','issue_type','dut','issue_description','socket_file_id'):
            if saved[key] != nullable(row[key]):
                raise ValueError('DBN source issue reconciliation failed: ' + key)
    for identity, digest in attachment_hashes.items():
        saved = ops.get_row(connection, 'repair_attachments', identity)
        if hashlib.sha256(saved['content']).hexdigest() != digest:
            raise ValueError('Attachment reconciliation failed')
    return dict(batch_id=batch, source_counts={table:len(rows) for table, rows in data.items()},
                operational_repairs=len(data['repair_records']), operational_dbn=len(data['dbn_records']),
                incomplete_dbn=sum(not row['issue_type'] for row in data['dbn_records']),
                source_history_imported=len(data['record_change_history']), attachments_verified=len(attachment_hashes),
                archive_only_tables=['repair_machines', 'repair_models'],
                repair_amount_cents=sum(reviewed.amount_cents(nullable(row['repair_amount'])) or 0 for row in data['repair_records']),
                null_amounts=sum(not row['repair_amount'] for row in data['repair_records']), warnings=warning_rows,
                archive='All 13 original CSV byte streams retained in SQLite; extra legacy fields are not editable business fields',
                derived_local_fields='DBN local version=1 and updated_at=source created_at; new mapping created_at=source updated_at; existing identical mappings retain local timestamps; originals remain archived',
                existing_data='No record overwrite; equal catalogs reused, different catalogs rejected')


def check(path, package):
    with tempfile.TemporaryDirectory(prefix='spms-legacy-check-') as directory:
        target = Path(directory) / 'preview.sqlite3'
        snapshot(path, target)
        with connect(target) as connection:
            connection.execute('BEGIN IMMEDIATE')
            result = import_into(connection, package)
        result['database_verification'] = verify(target)
        return result


def apply(path, package):
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        folder = Path(path).parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / ('before-legacy-import-' + uuid4().hex + '.sqlite3')
        snapshot(path, backup)
        result = import_into(connection, package)
    return dict(result, backup=str(backup))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build_cmd = commands.add_parser('build')
    build_cmd.add_argument('--csv-directory', type=Path, required=True)
    build_cmd.add_argument('--files-directory', type=Path, required=True)
    build_cmd.add_argument('--output', type=Path, required=True)
    build_cmd.add_argument('--description', required=True)
    import_cmd = commands.add_parser('import')
    import_cmd.add_argument('package', type=Path)
    import_cmd.add_argument('--database', type=Path, default=Path(__file__).resolve().parent / 'data/spms.sqlite3')
    import_cmd.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            package = build(args.csv_directory, args.files_directory, args.description)
            with args.output.open('x', encoding='utf-8') as handle:
                json.dump(package, handle, ensure_ascii=False)
            print('Created source bundle. Not imported:', args.output)
            return 0
        package = load(args.package)
        print('Package SHA256:', hashlib.sha256(args.package.read_bytes()).hexdigest())
        print(json.dumps(check(args.database, package), ensure_ascii=False, indent=2))
        if not args.apply:
            print('CHECK ONLY: original database unchanged.')
            return 0
        print('Stop SPMS. Review warnings. No overwrite/merge. A backup will be created before the transaction.')
        if input('Type IMPORT to confirm: ') != 'IMPORT':
            print('Cancelled.')
            return 0
        print(json.dumps(apply(args.database, package), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, csv.Error, sqlite3.Error, APIError) as error:
        print('LEGACY IMPORT FAILED:', error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('Cancelled.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
