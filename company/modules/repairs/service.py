"""Local spare-parts operations. All validation/auditing runs on the server."""
import json
import re
from datetime import date
from uuid import uuid4

from database import connect, sql_instant, utc_now
from errors import APIError

ACTIVE_STATUSES = ("待送修", "已送修", "取回驗證")
FAILURE_TAGS = ("INIT/DIAG", "RTE", "PBDATA", "CK", "LEAK", "OTHER", "AUTO SHUTDOWN", "OVER HEAT", "ZEBRA")
PRICE_COLUMNS = {"板修": "board_repair_cents", "外修": "external_repair_cents", "合約": "contract_repair_cents", "保固": "warranty_repair_cents"}
FIELDS = {"serial_no", "machine_code", "description", "board_part_code", "failure_tag", "failure_description",
          "repair_type", "current_status", "is_opened", "occurred_on", "sent_on", "returned_on"}


def normalize_serial(value):
    value = value.strip().upper()
    return value.zfill(9) if re.fullmatch(r"[0-9]{1,8}", value) else value


def public_record(row):
    result = dict(row)
    result["is_opened"] = bool(result["is_opened"])
    cents = result.pop("repair_amount_cents")
    result["repair_amount"] = None if cents is None else cents / 100
    return result


def audit(connection, source, record_id, operation, before, after):
    reference = after or before
    changes = {key: {"old": (before or {}).get(key), "new": (after or {}).get(key)}
               for key in set(before or {}) | set(after or {})
               if key not in ("id", "version", "created_at", "updated_at")
               and (before or {}).get(key) != (after or {}).get(key)}
    connection.execute("INSERT INTO record_change_history VALUES (?,?,?,?,?,?,?,?)", (
        str(uuid4()), source, record_id, operation, reference.get("serial_no"),
        reference.get("description", reference.get("board_name")), utc_now(),
        json.dumps(changes, ensure_ascii=False)))


def catalog(path):
    with connect(path) as connection:
        connection.execute('BEGIN')
        return {"machines": [dict(row) for row in connection.execute("SELECT * FROM repair_machine_models ORDER BY machine_code")],
                "boards": [dict(row) for row in connection.execute("SELECT * FROM repair_model_boards ORDER BY model, board_name")],
                "prices": [dict(row) for row in connection.execute('SELECT * FROM repair_board_prices ORDER BY model,board_name')],
                "statuses": list(ACTIVE_STATUSES), "failure_tags": list(FAILURE_TAGS), "repair_types": list(PRICE_COLUMNS)}


def serial_mapping(path, serial):
    serial = normalize_serial(serial)
    with connect(path) as connection:
        row = connection.execute("SELECT * FROM serial_board_mappings WHERE serial_no=?", (serial,)).fetchone()
        return {"data": dict(row) if row else None}


def list_records(path, query):
    text = query.get("q", [""])[0].strip()[:200]
    status = query.get("status", [""])[0]
    try:
        page = int(query.get("page", ["1"])[0])
    except ValueError:
        raise APIError("頁碼格式錯誤")
    if not 1 <= page <= 1000000:
        raise APIError("頁碼超過可接受範圍")
    where, arguments = [], []
    serial = query.get("serial", [""])[0].strip()
    if serial:
        where.append("serial_no=?")
        arguments.append(normalize_serial(serial))
    if text:
        text = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        fields = ('serial_no', 'description', 'board_part_code', 'machine_code', 'model', 'failure_description', 'failure_tag', 'repair_type')
        where.append('(' + ' OR '.join(field + " LIKE ? ESCAPE '\\'" for field in fields) + ')')
        arguments.extend([text] * len(fields))
    if status:
        if status not in (*ACTIVE_STATUSES, "結案（PASS）", "結案（FAIL）"):
            raise APIError("狀態無效")
        where.append("current_status=?")
        arguments.append(status)
    for field, allowed in (('failure_tag', FAILURE_TAGS), ('repair_type', PRICE_COLUMNS)):
        value = query.get(field, [''])[0]
        if value:
            if value not in allowed:
                raise APIError('篩選條件無效')
            where.append(field + '=?')
            arguments.append(value)
    condition = " WHERE " + " AND ".join(where) if where else ""
    with connect(path) as connection:
        # Keep the count and the page in the same read snapshot.
        connection.execute("BEGIN")
        total = connection.execute("SELECT count(*) FROM repair_records" + condition, arguments).fetchone()[0]
        counts = {row["current_status"]: row["count"] for row in connection.execute(
            "SELECT current_status, count(*) AS count FROM repair_records GROUP BY current_status")}
        page = min(page, max(1, (total + 19) // 20))
        rows = connection.execute("SELECT * FROM repair_records" + condition + " ORDER BY occurred_on DESC, " + sql_instant('created_at') + " DESC, id LIMIT 20 OFFSET ?",
                                  [*arguments, (page - 1) * 20]).fetchall()
        data = []
        for row in rows:
            count = connection.execute('SELECT count(*) FROM all_dbn_records WHERE serial_no=?', (row['serial_no'],)).fetchone()[0]
            data.append({**public_record(row), 'dbn_count': count})
        return {"data": data, "total": total, "page": page, "page_size": 20,
                "status_counts": counts}


def record_detail(path, record_id):
    with connect(path) as connection:
        row = connection.execute("SELECT * FROM repair_records WHERE id=?", (record_id,)).fetchone()
        if not row:
            raise APIError("找不到送修紀錄", 404)
        result = public_record(row)
        source = connection.execute("SELECT original_json,warnings FROM legacy_source_rows WHERE source_table='repair_records' AND source_key=?", (record_id,)).fetchone()
        if source:
            result['legacy_source'] = json.loads(source['original_json'])
            result['legacy_warnings'] = json.loads(source['warnings'])
        return {"data": result}


def validate(connection, payload, historical=False):
    if set(payload) - FIELDS:
        raise APIError("包含不支援的欄位，請重新載入頁面")
    result = {}
    for field in FIELDS - {"is_opened"}:
        value = payload.get(field, "待送修" if field == "current_status" else "")
        if value is None and field in ("sent_on", "returned_on"):
            value = ""
        if not isinstance(value, str):
            raise APIError(f"欄位格式錯誤：{field}")
        result[field] = value.strip()
    opened = payload.get("is_opened", False)
    if not isinstance(opened, bool):
        raise APIError("開單狀態格式錯誤")
    result["is_opened"] = int(opened)
    result["serial_no"] = normalize_serial(result["serial_no"])
    if not re.fullmatch(r"[^\x00-\x1f\x7f]{1,64}", result["serial_no"]):
        raise APIError("S/N 必填，最多 64 字元，不能包含控制字元")
    if not result["failure_description"] or len(result["failure_description"]) > 10000:
        raise APIError("異常描述必填，最多 10000 字元")
    if result["failure_tag"] not in FAILURE_TAGS:
        raise APIError("請選擇有效異常類別")
    if result["repair_type"] not in PRICE_COLUMNS:
        raise APIError("請選擇有效維修分類")
    if result["current_status"] not in ACTIVE_STATUSES:
        raise APIError("不能從編輯表單直接結案，請使用詳細資料中的 PASS／FAIL 操作")
    for field in ("occurred_on", "sent_on", "returned_on"):
        value = result[field]
        if not value:
            if field == "occurred_on":
                raise APIError("損壞日期必填")
            result[field] = None
        else:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise APIError("日期格式須為 YYYY-MM-DD")
    if result["current_status"] in ("已送修", "取回驗證") and not result["sent_on"]:
        raise APIError("已送修／取回驗證必須填送修日期")
    if result["current_status"] == "取回驗證" and not result["returned_on"]:
        raise APIError("取回驗證必須填回修日期")
    if not historical and result["sent_on"] and result["sent_on"] < result["occurred_on"]:
        raise APIError("送修日期不得早於損壞日期")
    if not historical and result["returned_on"] and (not result["sent_on"] or result["returned_on"] < result["sent_on"]):
        raise APIError("回修日期不得早於送修日期，且須有送修日期")
    machine = connection.execute("SELECT model FROM repair_machine_models WHERE machine_code=?", (result["machine_code"],)).fetchone()
    if not machine:
        raise APIError("機台不在目前對應表，請先確認對應資料")
    result["model"] = machine["model"]
    board = connection.execute("SELECT 1 FROM repair_model_boards WHERE model=? AND board_name=? AND board_part_code=?",
                               (result["model"], result["description"], result["board_part_code"])).fetchone()
    if not board:
        raise APIError("機型／板名／Part Number 組合無效")
    price = connection.execute("SELECT * FROM repair_board_prices WHERE model=? AND board_name=? AND board_part_code=?",
                               (result["model"], result["description"], result["board_part_code"])).fetchone()
    result["repair_amount_cents"] = price[PRICE_COLUMNS[result["repair_type"]]] if price else None
    return result


def save_record(path, payload, record_id=None):
    payload = dict(payload)
    expected = payload.pop("expected_version", None)
    reprice = payload.pop('reprice', False)
    if type(reprice) is not bool:
        raise APIError('重新套用價目須為布林值')
    attachment = payload.pop('attachment', None)
    if record_id and attachment is not None:
        raise APIError('編輯附件請使用附件操作')
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = None
        if record_id:
            row = connection.execute("SELECT * FROM repair_records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise APIError("找不到送修紀錄", 404)
            previous = public_record(row)
            if type(expected) is not int or expected != row["version"]:
                raise APIError("此紀錄已被其他人修改，請先重新載入；尚未儲存你的變更", 409)
            if row['current_status'] not in ACTIVE_STATUSES:
                if payload.get('current_status') != row['current_status']:
                    raise APIError('已結案案件不能從編輯表單重新開啟', 409)
                # Validate dates/context using the final active state, then retain closure.
                payload['current_status'] = '取回驗證'
        values = validate(connection, payload)
        # Ordinary edits preserve the recorded price, including NULL and zero.
        # Only an explicit reprice or a changed accounting identity uses today's catalog.
        accounting = ('model', 'description', 'board_part_code', 'repair_type')
        if previous and not reprice and all(values[key] == row[key] for key in accounting):
            values['repair_amount_cents'] = row['repair_amount_cents']
        if previous and previous['current_status'] not in ACTIVE_STATUSES:
            values['current_status'] = previous['current_status']
            if not previous['closed_on']:
                raise APIError('此案件缺少結案日期，請先確認日期', 409)
            if values['returned_on'] > previous['closed_on']:
                raise APIError('回修日期不得晚於結案日期')
        if not record_id and values["current_status"] != "待送修":
            raise APIError("新增案件須從待送修開始")
        now = utc_now()
        serial = values["serial_no"]
        mapping = connection.execute("SELECT * FROM serial_board_mappings WHERE serial_no=?", (serial,)).fetchone()
        if mapping and (mapping["board_name"] != values["description"] or mapping["board_part_code"] != values["board_part_code"]):
            raise APIError("S/N 主檔與板名／Part Number 衝突；不會覆寫主檔或歷史紀錄", 409)
        if not mapping:
            connection.execute("INSERT INTO serial_board_mappings (serial_no,board_name,board_part_code,created_at,updated_at) VALUES (?,?,?,?,?)",
                               (serial, values["description"], values["board_part_code"], now, now))
            audit(connection, "serial_board_mappings", serial, "INSERT", None,
                  {"serial_no": serial, "board_name": values["description"], "board_part_code": values["board_part_code"]})
        if record_id:
            values.update(updated_at=now, version=expected + 1)
            columns = ", ".join(field + "=?" for field in values)
            connection.execute("UPDATE repair_records SET " + columns + " WHERE id=? AND version=?",
                               [*values.values(), record_id, expected])
        else:
            record_id = str(uuid4())
            values.update(id=record_id, created_at=now, updated_at=now)
            columns = ", ".join(values)
            placeholders = ",".join("?" for _ in values)
            connection.execute(f"INSERT INTO repair_records ({columns}) VALUES ({placeholders})", list(values.values()))
        current = public_record(connection.execute("SELECT * FROM repair_records WHERE id=?", (record_id,)).fetchone())
        audit(connection, "repair_records", record_id, "UPDATE" if previous else "INSERT", previous, current)
        if attachment is not None:
            from . import attachments
            meta = attachments.insert(connection, record_id, attachment)
            audit(connection, 'repair_attachments', meta['id'], 'INSERT', None, {**meta, 'serial_no': current['serial_no']})
        return {"data": current}


def list_history(path, record_id):
    with connect(path) as connection:
        rows = connection.execute("SELECT * FROM record_change_history WHERE source_table='repair_records' AND record_id=? ORDER BY " + sql_instant('changed_at') + " DESC, id DESC", (record_id,))
        result = []
        for row in rows:
            entry = dict(row)
            entry["changes"] = json.loads(entry["changes"])
            result.append(entry)
        return {"data": result}
