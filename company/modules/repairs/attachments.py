"""Fail Logs live inside SQLite so writes, deletion and backups are atomic."""
import base64
import binascii
import hashlib
import re
from uuid import uuid4

from database import utc_now
from errors import APIError

MAX_FILE_SIZE = 5 * 1024 * 1024


def decode_upload(payload):
    if not isinstance(payload, dict) or set(payload) != {'filename', 'content_base64'}:
        raise APIError('附件須提供 filename 與 content_base64')
    filename = payload['filename']
    if (not isinstance(filename, str) or not re.fullmatch(r'[^/\\\x00-\x1f\x7f:]{1,180}', filename)
            or filename.rsplit('.', 1)[-1].lower() not in ('txt', 'asc')):
        raise APIError('只接受 .txt／.asc 檔名，不得包含路徑')
    encoded = payload['content_base64']
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_SIZE + 2) // 3):
        raise APIError('附件最大 5 MB', 413)
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise APIError('附件編碼錯誤')
    if not 0 < len(content) <= MAX_FILE_SIZE:
        raise APIError('附件不得為空，最大 5 MB', 413)
    return filename, content


def insert(connection, record_id, payload):
    filename, content = decode_upload(payload)
    if connection.execute('SELECT 1 FROM repair_attachments WHERE repair_record_id=?', (record_id,)).fetchone():
        raise APIError('每筆送修只限一個附件，請先刪除舊附件', 409)
    identity = str(uuid4())
    connection.execute('INSERT INTO repair_attachments VALUES (?,?,?,?,?,?)',
                       (identity, record_id, filename, content, hashlib.sha256(content).hexdigest(), utc_now()))
    return metadata(connection, record_id)


def metadata(connection, record_id):
    row = connection.execute('SELECT id, repair_record_id, filename, length(content) AS file_size, sha256, created_at FROM repair_attachments WHERE repair_record_id=?', (record_id,)).fetchone()
    return dict(row) if row else None
