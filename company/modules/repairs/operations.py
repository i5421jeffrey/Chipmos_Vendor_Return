"""Remaining local repair workflows. No cloud clients or network access."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from database import connect, utc_now
from errors import APIError
from . import attachments, service


def text(value, label, maximum=200, optional=False):
    if value is None and optional:
        return ''
    if not isinstance(value, str):
        raise APIError(f'{label}格式錯誤')
    value = value.strip()
    if (not value and not optional) or len(value) > maximum or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', value):
        raise APIError(f'{label}必填且不得超過 {maximum} 字元或包含控制字元')
    return value


def serial(value):
    result = service.normalize_serial(text(value, 'S/N', 64))
    if re.search(r'[\x00-\x1f\x7f]', result):
        raise APIError('S/N 不得包含控制字元')
    return result


def keys(payload, allowed):
    if set(payload) - set(allowed):
        raise APIError('包含不支援的欄位')


def version(row, expected):
    if type(expected) is not int or row['version'] != expected:
        raise APIError('此紀錄已被其他人修改，請重新載入；輸入尚未儲存', 409)


def get_row(connection, table, identity):
    # table is always an internal constant, never from a request.
    row = connection.execute(f'SELECT * FROM {table} WHERE id=?', (identity,)).fetchone()
    if not row:
        raise APIError('找不到此紀錄', 404)
    return row


def paginate(connection, table, query, columns, order, transform=dict):
    try:
        page = int(query.get('page', ['1'])[0])
    except ValueError:
        raise APIError('頁碼格式錯誤')
    if not 1 <= page <= 1000000:
        raise APIError('頁碼超出範圍')
    where, args = [], []
    if query.get('serial', [''])[0]:
        where.append('serial_no=?')
        args.append(serial(query['serial'][0]))
    q = query.get('q', [''])[0].strip()[:200]
    if q:
        where.append('(' + ' OR '.join(f"{column} LIKE ? ESCAPE '\\'" for column in columns) + ')')
        args.extend(['%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'] * len(columns))
    condition = ' WHERE ' + ' AND '.join(where) if where else ''
    total = connection.execute(f'SELECT count(*) FROM {table}' + condition, args).fetchone()[0]
    page = min(page, max(1, (total + 19) // 20))
    rows = connection.execute(f'SELECT * FROM {table}' + condition + f' ORDER BY {order} LIMIT 20 OFFSET ?', [*args, (page - 1) * 20])
    return dict(data=[transform(row) for row in rows], total=total, page=page, page_size=20)


def ensure_mapping(connection, values):
    number, name, part = values['serial_no'], values['board_name'], values['board_part_code']
    row = connection.execute('SELECT * FROM serial_board_mappings WHERE serial_no=?', (number,)).fetchone()
    if row and (row['board_name'], row['board_part_code']) != (name, part):
        raise APIError('S/N 主檔與板名／Part Number 衝突', 409)
    if not row:
        now = utc_now()
        connection.execute('INSERT INTO serial_board_mappings VALUES (?,?,?,?,?,1)', (number, name, part, now, now))
        service.audit(connection, 'serial_board_mappings', number, 'INSERT', None,
                      dict(serial_no=number, board_name=name, board_part_code=part))


def board_context(connection, machine, name, part):
    row = connection.execute('SELECT model FROM repair_machine_models WHERE machine_code=?', (machine,)).fetchone()
    if not row or not connection.execute('SELECT 1 FROM repair_model_boards WHERE model=? AND board_name=? AND board_part_code=?', (row['model'], name, part)).fetchone():
        raise APIError('機台／機型／板名／Part Number 組合無效')
    return row['model']


def dbn_catalog(path):
    with connect(path) as connection:
        connection.execute('BEGIN')
        return dict(customers=[row[0] for row in connection.execute('SELECT customer_code FROM dbn_customers ORDER BY customer_code')],
                    combinations=[dict(row) for row in connection.execute('SELECT * FROM dbn_valid_combinations ORDER BY customer_code,product_code,station_code')],
                    sockets=[{**dict(row), 'dut_pins': json.loads(row['dut_pins'])} for row in connection.execute('SELECT * FROM dbn_socket_files')])


def public_dbn(row):
    result = dict(row)
    result['dut_pin_snapshot'] = json.loads(result['dut_pin_snapshot'])
    return result


def list_dbn(path, query):
    with connect(path) as connection:
        connection.execute('BEGIN')
        return paginate(connection, 'dbn_records', query, ('serial_no', 'board_name', 'machine_code', 'customer_code', 'product_code', 'issue_description'), 'created_at DESC,id', public_dbn)


def serial_summary(path, number):
    number = serial(number)
    with connect(path) as connection:
        connection.execute('BEGIN')
        rows = connection.execute('SELECT machine_code,model FROM repair_records WHERE serial_no=? UNION SELECT machine_code,model FROM dbn_records WHERE serial_no=?', (number, number)).fetchall()
        mapping = connection.execute('SELECT board_name,board_part_code FROM serial_board_mappings WHERE serial_no=?', (number,)).fetchone()
        return dict(serial_no=number, mapping=dict(mapping) if mapping else None,
                    machines=sorted({row['machine_code'] for row in rows}), models=sorted({row['model'] for row in rows}))


def validate_issue(payload, socket=None, previous=None):
    kind = payload.get('issue_type')
    if kind not in ('Group', 'Single Dut', 'RTE', 'Other'):
        raise APIError('請選擇 DBN 類型')
    if kind in ('RTE', 'Other'):
        return dict(issue_type=kind, dut=None, issue_description=text(payload.get('issue_description'), '異常描述', 10000),
                    socket_file_id=None, dut_pin_snapshot='{}')
    dut = re.sub(r'\s*-\s*', '-', text(payload.get('dut'), 'DUT', 12))
    if not re.fullmatch(r'\d{1,4}(?:-\d{1,4})?', dut):
        raise APIError('DUT 請填單一編號或連續範圍')
    first, last = (int(dut.split('-')[0]), int(dut.split('-')[-1]))
    if not 1 <= first <= last <= 2048 or (kind == 'Group' and last - first >= 8) or (kind == 'Single Dut' and '-' in dut):
        raise APIError('Single Dut 限單一編號；Group 限連續 1–8 個 DUT，編號 1–2048')
    canonical = str(first) if first == last else f'{first}-{last}'
    # Preserve historical snapshots if the product and DUT have not changed.
    if previous and previous['product_code'] == payload.get('product_code') and previous['dut'] == canonical:
        snapshot, identity = previous['dut_pin_snapshot'], previous['socket_file_id']
    else:
        if socket and last > socket['dut_count']:
            raise APIError('DUT 超出此 Socket File 範圍')
        pins = json.loads(socket['dut_pins']) if socket else {}
        snapshot = json.dumps({str(n): pins.get(str(n)) for n in range(first, last + 1)}, ensure_ascii=False)
        identity = socket['id'] if socket else None
    return dict(issue_type=kind, dut=canonical, issue_description=None, socket_file_id=identity, dut_pin_snapshot=snapshot)


def save_dbn(path, payload, identity=None):
    keys(payload, ('serial_no', 'machine_code', 'board_name', 'board_part_code', 'customer_code', 'product_code', 'station_code', 'issue_type', 'dut', 'issue_description', 'expected_version'))
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = get_row(connection, 'dbn_records', identity) if identity else None
        if previous:
            version(previous, payload.get('expected_version'))
        values = {key: text(payload.get(key), key) for key in ('machine_code', 'board_name', 'board_part_code', 'customer_code')}
        values['serial_no'] = serial(payload.get('serial_no'))
        values['model'] = board_context(connection, values['machine_code'], values['board_name'], values['board_part_code'])
        if not connection.execute('SELECT 1 FROM dbn_customers WHERE customer_code=?', (values['customer_code'],)).fetchone():
            raise APIError('客戶無效')
        for key in ('product_code', 'station_code'):
            values[key] = text(payload.get(key), key, optional=True) or None
        has_products = connection.execute('SELECT 1 FROM dbn_valid_combinations WHERE customer_code=?', (values['customer_code'],)).fetchone()
        if has_products:
            if not connection.execute('SELECT 1 FROM dbn_valid_combinations WHERE customer_code=? AND product_code=? AND station_code=?', (values['customer_code'], values['product_code'], values['station_code'])).fetchone():
                raise APIError('客戶／產品／站點組合無效')
        elif values['product_code'] or values['station_code']:
            raise APIError('此客戶無產品／站點，請留白')
        socket = connection.execute('SELECT * FROM dbn_socket_files WHERE product_code=?', (values['product_code'],)).fetchone()
        values.update(validate_issue({**payload, 'product_code': values['product_code']}, socket, previous))
        ensure_mapping(connection, values)
        now = utc_now()
        if identity:
            values.update(updated_at=now, version=previous['version'] + 1)
            connection.execute('UPDATE dbn_records SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?', [*values.values(), identity])
        else:
            identity = str(uuid4())
            values.update(id=identity, created_at=now, updated_at=now)
            connection.execute('INSERT INTO dbn_records (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))
        current = public_dbn(get_row(connection, 'dbn_records', identity))
        service.audit(connection, 'dbn_records', identity, 'UPDATE' if previous else 'INSERT', public_dbn(previous) if previous else None, current)
        return {'data': current}


def resolve(path, identity, payload):
    keys(payload, ('expected_version', 'passed', 'failure_description', 'repair_type', 'attachment'))
    if type(payload.get('passed')) is not bool:
        raise APIError('passed 須為布林值')
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = get_row(connection, 'repair_records', identity)
        version(row, payload.get('expected_version'))
        if row['current_status'] != '取回驗證' or row['repair_amount_cents'] is None or not row['returned_on']:
            raise APIError('僅能結案取回驗證且金額已設定的案件（零元可結案）', 409)
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        if today < row['returned_on']:
            raise APIError('回修日期在未來，不能結案')
        before = service.public_record(row)
        status = '結案（PASS）' if payload['passed'] else '結案（FAIL）'
        if payload['passed'] and set(payload) - {'expected_version', 'passed'}:
            raise APIError('PASS 不接受再次送修內容')
        connection.execute('UPDATE repair_records SET current_status=?,closed_on=?,updated_at=?,version=version+1 WHERE id=?', (status, today, utc_now(), identity))
        after = service.public_record(get_row(connection, 'repair_records', identity))
        service.audit(connection, 'repair_records', identity, 'UPDATE', before, after)
        retry = None
        if not payload['passed']:
            values = {key: before[key] for key in service.FIELDS}
            values.update(current_status='待送修', is_opened=False, occurred_on=today, sent_on=None, returned_on=None,
                          failure_description=text(payload.get('failure_description'), '本次異常描述', 10000),
                          repair_type=payload.get('repair_type'))
            values = service.validate(connection, values)
            ensure_mapping(connection, {**values, 'board_name': values['description']})
            new_id, now = str(uuid4()), utc_now()
            values.update(id=new_id, retry_of_record_id=identity, created_at=now, updated_at=now)
            connection.execute('INSERT INTO repair_records (' + ','.join(values) + ') VALUES (' + ','.join('?' for _ in values) + ')', list(values.values()))
            retry = service.public_record(get_row(connection, 'repair_records', new_id))
            service.audit(connection, 'repair_records', new_id, 'INSERT', None, retry)
            if payload.get('attachment') is not None:
                meta = attachments.insert(connection, new_id, payload['attachment'])
                service.audit(connection, 'repair_attachments', meta['id'], 'INSERT', None, {**meta, 'serial_no': row['serial_no']})
        return dict(data=after, retry=retry)


def chain(path, identity):
    with connect(path) as connection:
        connection.execute('BEGIN')
        row = get_row(connection, 'repair_records', identity)
        seen = set()
        while row['retry_of_record_id'] and row['id'] not in seen:
            seen.add(row['id'])
            row = get_row(connection, 'repair_records', row['retry_of_record_id'])
        result, seen = [], set()
        while row and row['id'] not in seen:
            seen.add(row['id'])
            result.append({**service.public_record(row), 'attachment': attachments.metadata(connection, row['id'])})
            row = connection.execute('SELECT * FROM repair_records WHERE retry_of_record_id=?', (row['id'],)).fetchone()
        return {'data': result}


def attachment_metadata(path, identity):
    with connect(path) as connection:
        get_row(connection, 'repair_records', identity)
        return {'data': attachments.metadata(connection, identity)}


def attachment_content(path, identity):
    with connect(path) as connection:
        row = connection.execute('SELECT * FROM repair_attachments WHERE id=?', (identity,)).fetchone()
        if not row:
            raise APIError('找不到附件', 404)
        return dict(row)


def upload_attachment(path, identity, payload):
    keys(payload, ('expected_version', 'attachment'))
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = get_row(connection, 'repair_records', identity)
        version(row, payload.get('expected_version'))
        meta = attachments.insert(connection, identity, payload.get('attachment'))
        connection.execute('UPDATE repair_records SET version=version+1,updated_at=? WHERE id=?', (utc_now(), identity))
        service.audit(connection, 'repair_attachments', meta['id'], 'INSERT', None, {**meta, 'serial_no': row['serial_no']})
        service.audit(connection, 'repair_records', identity, 'UPDATE', {**service.public_record(row), 'attachment': None},
                      {**service.public_record(get_row(connection, 'repair_records', identity)), 'attachment': meta})
        return {'data': meta}


def delete(path, kind, identity, payload):
    keys(payload, ('expected_version',))
    if kind not in ('records', 'dbn', 'attachments'):
        raise APIError('不支援刪除', 405)
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        if kind == 'attachments':
            row = get_row(connection, 'repair_attachments', identity)
            parent = get_row(connection, 'repair_records', row['repair_record_id'])
            version(parent, payload.get('expected_version'))
            before = {**attachments.metadata(connection, parent['id']), 'serial_no': parent['serial_no']}
            connection.execute('DELETE FROM repair_attachments WHERE id=?', (identity,))
            connection.execute('UPDATE repair_records SET version=version+1,updated_at=? WHERE id=?', (utc_now(), parent['id']))
            service.audit(connection, 'repair_attachments', identity, 'DELETE', before, None)
            service.audit(connection, 'repair_records', parent['id'], 'UPDATE', {**service.public_record(parent), 'attachment': before},
                          {**service.public_record(get_row(connection, 'repair_records', parent['id'])), 'attachment': None})
        else:
            table = 'repair_records' if kind == 'records' else 'dbn_records'
            row = get_row(connection, table, identity)
            version(row, payload.get('expected_version'))
            if kind == 'records' and (row['retry_of_record_id'] or connection.execute('SELECT 1 FROM repair_records WHERE retry_of_record_id=?', (identity,)).fetchone()):
                raise APIError('此筆屬於連續送修鏈，為保留歷史關聯不允許刪除', 409)
            if kind == 'records':
                meta = attachments.metadata(connection, identity)
                if meta:
                    service.audit(connection, 'repair_attachments', meta['id'], 'DELETE', {**meta, 'serial_no': row['serial_no']}, None)
            before = service.public_record(row) if kind == 'records' else public_dbn(row)
            connection.execute(f'DELETE FROM {table} WHERE id=?', (identity,))
            service.audit(connection, table, identity, 'DELETE', before, None)
        return {'deleted': identity}


def list_mappings(path, query):
    with connect(path) as connection:
        connection.execute('BEGIN')
        return paginate(connection, 'serial_board_mappings', query, ('serial_no', 'board_name', 'board_part_code'), 'serial_no')


def mapping_impact(connection, payload):
    old = serial(payload.get('previous_serial_no') or payload.get('serial_no'))
    new = serial(payload.get('serial_no'))
    name = text(payload.get('board_name'), '板名')
    part = text(payload.get('board_part_code'), 'Part Number')
    rows = {}
    for table, field in (('repair_records', 'description'), ('dbn_records', 'board_name')):
        rows[table] = [dict(row) for row in connection.execute(f'SELECT * FROM {table} WHERE serial_no=? AND (serial_no<>? OR {field}<>? OR board_part_code<>?) ORDER BY id', (old, new, name, part))]
    token = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(repair_count=len(rows['repair_records']), dbn_count=len(rows['dbn_records']), token=token), rows


def preview_mapping(path, payload):
    keys(payload, ('previous_serial_no', 'serial_no', 'board_name', 'board_part_code'))
    with connect(path) as connection:
        connection.execute('BEGIN')
        return mapping_impact(connection, payload)[0]


def save_mapping(path, payload):
    keys(payload, ('previous_serial_no', 'serial_no', 'board_name', 'board_part_code', 'expected_version', 'sync_history', 'impact_token'))
    if type(payload.get('sync_history')) is not bool:
        raise APIError('請明確選擇是否同步歷史')
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        impact, rows = mapping_impact(connection, payload)
        if payload.get('impact_token') != impact['token']:
            raise APIError('歷史紀錄已變更，請重新預覽受影響筆數', 409)
        number = serial(payload.get('serial_no'))
        previous_number = serial(payload.get('previous_serial_no') or number)
        previous = connection.execute('SELECT * FROM serial_board_mappings WHERE serial_no=?', (previous_number,)).fetchone()
        if previous:
            version(previous, payload.get('expected_version'))
        elif payload.get('previous_serial_no') or payload.get('expected_version') is not None:
            raise APIError('主檔已變更，請重新載入', 409)
        if number != previous_number and connection.execute('SELECT 1 FROM serial_board_mappings WHERE serial_no=?', (number,)).fetchone():
            raise APIError('新 S/N 已存在，不能合併或覆蓋', 409)
        name, part = text(payload.get('board_name'), '板名'), text(payload.get('board_part_code'), 'Part Number')
        if not connection.execute('SELECT 1 FROM repair_model_boards WHERE board_name=? AND board_part_code=?', (name, part)).fetchone():
            raise APIError('板名／Part Number 不在對應表')
        now = utc_now()
        if previous and number == previous_number:
            connection.execute('UPDATE serial_board_mappings SET board_name=?,board_part_code=?,version=version+1,updated_at=? WHERE serial_no=?', (name, part, now, number))
        else:
            connection.execute('INSERT INTO serial_board_mappings VALUES (?,?,?,?,?,1)', (number, name, part, now, now))
        current = dict(connection.execute('SELECT * FROM serial_board_mappings WHERE serial_no=?', (number,)).fetchone())
        service.audit(connection, 'serial_board_mappings', number, 'UPDATE' if previous and number == previous_number else 'INSERT', dict(previous) if previous and number == previous_number else None, current)
        if payload['sync_history']:
            for table, affected in rows.items():
                for row in affected:
                    if not connection.execute('SELECT 1 FROM repair_model_boards WHERE model=? AND board_name=? AND board_part_code=?', (row['model'], name, part)).fetchone():
                        raise APIError('同步板件與歷史 Model 不相容；已取消全部修改')
                    before = service.public_record(row) if table == 'repair_records' else public_dbn(row)
                    field = 'description' if table == 'repair_records' else 'board_name'
                    # Deliberately preserve all historical prices and Socket snapshots.
                    connection.execute(f'UPDATE {table} SET serial_no=?,{field}=?,board_part_code=?,version=version+1,updated_at=? WHERE id=?', (number, name, part, now, row['id']))
                    after_row = get_row(connection, table, row['id'])
                    after = service.public_record(after_row) if table == 'repair_records' else public_dbn(after_row)
                    service.audit(connection, table, row['id'], 'UPDATE', before, after)
        if previous and number != previous_number:
            referenced = any(connection.execute(f'SELECT 1 FROM {table} WHERE serial_no=?', (previous_number,)).fetchone() for table in ('repair_records', 'dbn_records'))
            if not referenced:
                connection.execute('DELETE FROM serial_board_mappings WHERE serial_no=?', (previous_number,))
                service.audit(connection, 'serial_board_mappings', previous_number, 'DELETE', dict(previous), None)
        return dict(data=current, impact=impact)


def history(path, query):
    with connect(path) as connection:
        connection.execute('BEGIN')
        def decode(row):
            return {**dict(row), 'changes': json.loads(row['changes'])}
        return paginate(connection, 'record_change_history', query, ('serial_no', 'board_name', 'source_table', 'operation'), 'changed_at DESC,id DESC', decode)


def statistics(path, query):
    mode, period = query.get('mode', ['year'])[0], query.get('period', [str(datetime.now().year)])[0]
    if mode not in ('year', 'month') or not re.fullmatch(r'\d{4}' if mode == 'year' else r'(?:0[1-9]|1[0-2])', period):
        raise APIError('年／月篩選格式錯誤')
    with connect(path) as connection:
        connection.execute('BEGIN')
        years = sorted({str(datetime.now().year)} | {row[0] for row in connection.execute("SELECT substr(occurred_on,1,4) FROM repair_records UNION SELECT substr(closed_on,1,4) FROM repair_records WHERE closed_on IS NOT NULL")})
        buckets = [f'{period}-{month:02}' for month in range(1, 13)] if mode == 'year' else [f'{year}-{period}' for year in years]
        frequency = dict.fromkeys(buckets, 0)
        amounts = {bucket: dict.fromkeys(service.PRICE_COLUMNS, 0) for bucket in buckets}
        ranking, missing = {}, 0
        for row in connection.execute('SELECT * FROM repair_records'):
            occurred = row['occurred_on'][:7]
            if not row['retry_of_record_id'] and occurred in frequency:
                frequency[occurred] += 1
                ranking[row['machine_code']] = ranking.get(row['machine_code'], 0) + 1
            closed = (row['closed_on'] or '')[:7]
            if row['current_status'] in ('結案（PASS）', '結案（FAIL）') and closed in amounts:
                if row['repair_amount_cents'] is None:
                    missing += 1
                else:
                    amounts[closed][row['repair_type']] += row['repair_amount_cents']
        return dict(years=years, frequency=frequency, amounts_cents=amounts, missing_amounts=missing,
                    ranking=sorted((dict(machine=key, count=value) for key, value in ranking.items()), key=lambda row: (-row['count'], row['machine'])))


def masters(path):
    with connect(path) as connection:
        connection.execute('BEGIN')
        rows = {name: [dict(row) for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY 1,2')] for name, table in
                (('machines', 'repair_machine_models'), ('boards', 'repair_model_boards'), ('prices', 'repair_board_prices'))}
        return {**rows, 'token': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def save_master(path, payload):
    keys(payload, ('kind', 'value', 'expected_token'))
    kind, value = payload.get('kind'), payload.get('value')
    if kind not in ('machine', 'board', 'price') or not isinstance(value, dict):
        raise APIError('主檔種類／內容錯誤')
    with connect(path) as connection:
        connection.execute('BEGIN IMMEDIATE')
        # A second connection is safe for this read; writer holds the reservation.
        if payload.get('expected_token') != masters(path)['token']:
            raise APIError('主檔已變更，請重新載入', 409)
        model = text(value.get('model'), 'Model', 64)
        if kind == 'machine':
            keys(value, ('machine_code', 'model'))
            code = text(value.get('machine_code'), '機台', 64)
            old = connection.execute('SELECT * FROM repair_machine_models WHERE machine_code=?', (code,)).fetchone()
            connection.execute('INSERT INTO repair_machine_models VALUES (?,?) ON CONFLICT(machine_code) DO UPDATE SET model=excluded.model', (code, model))
            after = dict(machine_code=code, model=model)
            identity, table = code, 'repair_machine_models'
        else:
            name, part = text(value.get('board_name'), '板名'), text(value.get('board_part_code'), 'Part Number')
            if kind == 'board':
                keys(value, ('model', 'board_name', 'board_part_code'))
                old = connection.execute('SELECT * FROM repair_model_boards WHERE model=? AND board_name=?', (model, name)).fetchone()
                connection.execute('INSERT INTO repair_model_boards VALUES (?,?,?) ON CONFLICT(model,board_name) DO UPDATE SET board_part_code=excluded.board_part_code', (model, name, part))
                after = dict(model=model, board_name=name, board_part_code=part)
                table = 'repair_model_boards'
            else:
                keys(value, ('model', 'board_name', 'board_part_code', *service.PRICE_COLUMNS.values()))
                if not connection.execute('SELECT 1 FROM repair_model_boards WHERE model=? AND board_name=? AND board_part_code=?', (model, name, part)).fetchone():
                    raise APIError('請先建立板件對應')
                amounts = []
                for column in service.PRICE_COLUMNS.values():
                    amount = value.get(column)
                    if amount is not None and (type(amount) is not int or not 0 <= amount <= 10**12):
                        raise APIError('價格須為整數分，空白是未設定')
                    amounts.append(amount)
                if amounts[-1] not in (None, 0):
                    raise APIError('保固金額只能是零或未設定')
                old = connection.execute('SELECT * FROM repair_board_prices WHERE model=? AND board_name=? AND board_part_code=?', (model, name, part)).fetchone()
                columns = list(service.PRICE_COLUMNS.values())
                connection.execute('INSERT INTO repair_board_prices VALUES (?,?,?,?,?,?,?) ON CONFLICT(model,board_name,board_part_code) DO UPDATE SET ' + ','.join(f'{col}=excluded.{col}' for col in columns), (model, name, part, *amounts))
                after = dict(model=model, board_name=name, board_part_code=part, **dict(zip(columns, amounts)))
                table = 'repair_board_prices'
            identity = json.dumps([model, name, part], ensure_ascii=False)
        service.audit(connection, table, identity, 'UPDATE' if old else 'INSERT', dict(old) if old else None, after)
        return {'data': after}
