"""Validate/apply a reviewed offline JSON package, without connecting to Supabase.

Not a raw SQL/CSV importer. See README for the explicit interchange format.
Default is a dry run against a temporary SQLite copy; --apply still prompts.
Existing records are never overwritten or merged. Any error rolls back the batch.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from database import connect, utc_now
from errors import APIError
from maintenance import snapshot
from modules.repairs import attachments, operations as ops, service


def package_from_bytes(raw):
    if len(raw) > 100 * 1024 * 1024:
        raise ValueError('Package exceeds 100 MB; split into reviewed batches')
    data = json.loads(raw)
    allowed = {'format', 'source_description', 'serial_board_mappings', 'repair_records', 'dbn_records', 'repair_attachments'}
    if not isinstance(data, dict) or set(data) - allowed or data.get('format') != 'spms-offline-import-v1':
        raise ValueError('Expected reviewed spms-offline-import-v1 JSON package')
    ops.text(data.get('source_description'), 'source_description', 2000)
    for key in allowed - {'format', 'source_description'}:
        if not isinstance(data.get(key, []), list) or any(not isinstance(row, dict) for row in data.get(key, [])):
            raise ValueError('Every table must be an array of objects')
    return data


def amount_cents(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise APIError('匯入金額格式錯誤')
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or not 0 <= amount <= 10**12 or amount != amount.to_integral_value():
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise APIError('匯入金額須為非負數，最多兩位小數；未設定須明確為 null')


def iso_date(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise APIError('匯入日期須為 YYYY-MM-DD')
    return value


def timestamp(value, fallback):
    if value is None:
        return fallback
    try:
        if not isinstance(value, str) or len(value) > 64 or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError()
    except ValueError:
        raise APIError('來源時間須包含時區的 ISO 時間字串')
    return value


def identity(value):
    value = ops.text(value, '來源 ID', 64)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise APIError('來源 ID 只接受英數、連字號或底線（UUID 可直接保留）')
    return value


def insert(connection, table, values):
    connection.execute('INSERT INTO ' + table + '(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', list(values.values()))


def import_rows(connection, package):
    connection.execute('PRAGMA defer_foreign_keys=ON')
    now = utc_now()
    counts = {}
    for row in package.get('serial_board_mappings', []):
        ops.keys(row, ('serial_no', 'board_name', 'board_part_code'))
        values = dict(serial_no=ops.serial(row.get('serial_no')), board_name=ops.text(row.get('board_name'), '板名'), board_part_code=ops.text(row.get('board_part_code'), 'Part Number'))
        if not connection.execute('SELECT 1 FROM repair_model_boards WHERE board_name=? AND board_part_code=?', (values['board_name'], values['board_part_code'])).fetchone():
            raise APIError('匯入主檔板件不在對應表，請先核對並建立基礎對應')
        ops.ensure_mapping(connection, values)
    repair_ids = []
    for row in package.get('repair_records', []):
        ops.keys(row, (*service.FIELDS, 'id', 'repair_amount', 'closed_on', 'retry_of_record_id', 'created_at', 'updated_at'))
        if 'repair_amount' not in row:
            raise APIError('匯入必須明確提供 repair_amount（可為 null），不會用目前價目取代歷史金額')
        record_id = identity(row.get('id'))
        status = row.get('current_status')
        closed = status in ('結案（PASS）', '結案（FAIL）')
        fields = {key: row[key] for key in service.FIELDS if key in row}
        if closed:
            fields['current_status'] = '取回驗證'
        values = service.validate(connection, fields)
        values['current_status'] = status or values['current_status']
        values['repair_amount_cents'] = amount_cents(row['repair_amount'])
        if values['repair_type'] == '保固' and values['repair_amount_cents'] not in (None, 0):
            raise APIError('保固金額只能為零或未設定')
        closed_on = iso_date(row.get('closed_on')) if closed else None
        if closed and closed_on < values['returned_on']:
            raise APIError('結案日期不得早於回修日期')
        if not closed and row.get('closed_on'):
            raise APIError('未結案案件不能有結案日期')
        ops.ensure_mapping(connection, {**values, 'board_name': values['description']})
        parent = identity(row['retry_of_record_id']) if row.get('retry_of_record_id') else None
        values.update(id=record_id, closed_on=closed_on, retry_of_record_id=parent,
                      created_at=timestamp(row.get('created_at'), now), updated_at=timestamp(row.get('updated_at'), now))
        insert(connection, 'repair_records', values)
        service.audit(connection, 'repair_records', record_id, 'IMPORT', None, service.public_record(ops.get_row(connection, 'repair_records', record_id)))
        repair_ids.append(record_id)
    # Verify every imported retry chain, including parent status/context and cycles.
    for record_id in repair_ids:
        row = ops.get_row(connection, 'repair_records', record_id)
        seen = set()
        while row['retry_of_record_id']:
            if row['id'] in seen:
                raise APIError('匯入的再次送修鏈有循環')
            seen.add(row['id'])
            parent = ops.get_row(connection, 'repair_records', row['retry_of_record_id'])
            if parent['current_status'] != '結案（FAIL）' or parent['serial_no'] != row['serial_no'] or parent['closed_on'] > row['occurred_on']:
                raise APIError('匯入的再次送修鏈缺少 FAIL 前次案件或日期／S/N 不符')
            row = parent
    for row in package.get('dbn_records', []):
        allowed = ('id','serial_no','machine_code','board_name','board_part_code','customer_code','product_code','station_code','issue_type','dut','issue_description','socket_file_id','dut_pin_snapshot','created_at','updated_at')
        ops.keys(row, allowed)
        record_id = identity(row.get('id'))
        values = {key: ops.text(row.get(key), key) for key in ('machine_code','board_name','board_part_code','customer_code')}
        if connection.execute('SELECT 1 FROM all_dbn_records WHERE id=?', (record_id,)).fetchone():
            raise APIError('DBN ID 已存在，不覆寫包含未補齊類型的來源舊案', 409)
        values['serial_no'] = ops.serial(row.get('serial_no'))
        values['model'] = ops.board_context(connection, values['machine_code'], values['board_name'], values['board_part_code'])
        customer = values['customer_code']
        if not connection.execute('SELECT 1 FROM dbn_customers WHERE customer_code=?', (customer,)).fetchone():
            raise APIError('匯入 DBN 客戶無效')
        for key in ('product_code','station_code'):
            values[key] = ops.text(row.get(key), key, optional=True) or None
        has_products = connection.execute('SELECT 1 FROM dbn_valid_combinations WHERE customer_code=?', (customer,)).fetchone()
        if has_products and not connection.execute('SELECT 1 FROM dbn_valid_combinations WHERE customer_code=? AND product_code=? AND station_code=?', (customer,values['product_code'],values['station_code'])).fetchone():
            raise APIError('匯入 DBN 產品／站點組合無效')
        if not has_products and (values['product_code'] or values['station_code']):
            raise APIError('此客戶不接受產品／站點')
        issue = ops.validate_issue(row)
        snapshot = row.get('dut_pin_snapshot')
        if not isinstance(snapshot, dict):
            raise APIError('匯入 DBN 必須明確提供歷史 dut_pin_snapshot，不得以目前 Socket 重建')
        if issue['dut']:
            if set(snapshot) != set(json.loads(issue['dut_pin_snapshot'])):
                raise APIError('歷史 PIN 快照 DUT 與選取範圍不符')
            for pins in snapshot.values():
                if pins is not None and (not isinstance(pins, list) or len(pins) > 10000 or any(not isinstance(pin, str) or not 1 <= len(pin) <= 200 for pin in pins)):
                    raise APIError('歷史 PIN 快照格式無效')
        elif snapshot or row.get('socket_file_id'):
            raise APIError('RTE／Other 不接受 DUT 快照')
        issue.update(dut_pin_snapshot=json.dumps(snapshot, ensure_ascii=False), socket_file_id=ops.text(row.get('socket_file_id'), 'Socket ID', 128, optional=True) or None)
        values.update(issue, id=record_id, created_at=timestamp(row.get('created_at'), now), updated_at=timestamp(row.get('updated_at'), now))
        ops.ensure_mapping(connection, values)
        insert(connection, 'dbn_records', values)
        service.audit(connection, 'dbn_records', record_id, 'IMPORT', None, ops.public_dbn(ops.get_row(connection, 'dbn_records', record_id)))
    for row in package.get('repair_attachments', []):
        ops.keys(row, ('repair_record_id','filename','content_base64'))
        record_id = identity(row.get('repair_record_id'))
        record = ops.get_row(connection, 'repair_records', record_id)
        meta = attachments.insert(connection, record_id, {key: row[key] for key in ('filename','content_base64') if key in row})
        connection.execute('UPDATE repair_records SET version=version+1,updated_at=? WHERE id=?', (now, record_id))
        service.audit(connection, 'repair_attachments', meta['id'], 'IMPORT', None, {**meta, 'serial_no':record['serial_no']})
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise APIError('匯入關聯驗證失敗')
    for key in ('serial_board_mappings','repair_records','dbn_records','repair_attachments'):
        counts[key] = len(package.get(key, []))
    return counts


def check(path, package):
    with tempfile.TemporaryDirectory(prefix='spms-import-check-') as folder:
        temporary = Path(folder) / 'preview.sqlite3'
        snapshot(path, temporary)
        with connect(temporary) as connection:
            connection.execute('BEGIN IMMEDIATE')
            return import_rows(connection, package)


def apply(path, package):
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        backup = Path(path).parent / 'backups'
        backup.mkdir(exist_ok=True)
        output = backup / ('before-import-' + uuid4().hex + '.sqlite3')
        # The reservation prevents other writers between the backup and commit.
        snapshot(path, output)
        result = import_rows(connection, package)
        return dict(counts=result, backup=str(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--database', type=Path, default=Path(__file__).resolve().parent / 'data/spms.sqlite3')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        raw = args.package.read_bytes()
        package = package_from_bytes(raw)
        print('Package SHA256:', hashlib.sha256(raw).hexdigest())
        print('Source:', package['source_description'])
        print('Validated:', check(args.database, package))
        if not args.apply:
            print('CHECK OK. Original database unchanged. Temporary validation copy discarded.')
            return 0
        print('Stop SPMS first. Existing records are never overwritten; errors roll back the entire batch.')
        if input('Type IMPORT to confirm, anything else to cancel: ') != 'IMPORT':
            print('Cancelled. Original unchanged.')
            return 0
        print(apply(args.database, package))
        print('IMPORT OK. Preserve the source package and verify counts, prices, chains and attachments.')
        return 0
    except (OSError, sqlite3.Error, ValueError, APIError) as error:
        print('IMPORT FAILED:', error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('Cancelled.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
