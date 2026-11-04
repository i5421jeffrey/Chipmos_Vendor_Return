"""Shared-password accidental-edit guard, not individual user authentication."""
import argparse
import getpass
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from errors import APIError


def password_hash(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1).hex()


def configure(path, password):
    if not isinstance(password, str) or not 1 <= len(password) <= 200:
        raise ValueError('密碼須為 1–200 字元')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(16)
    value = dict(format='spms-edit-password-v1', salt=salt.hex(), digest=password_hash(password, salt))
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class EditGate:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.sessions = {}
        self.failures = 0
        self.blocked_until = 0
        self.fingerprint = None

    def settings(self):
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            raw = b''
        except OSError:
            raise APIError('無法讀取編輯密碼設定，請聯絡管理人員', 503)
        fingerprint = hashlib.sha256(raw).hexdigest()
        if self.fingerprint != fingerprint:
            self.sessions.clear()
            self.fingerprint = fingerprint
        if not raw:
            return None
        try:
            value = json.loads(raw)
            if value['format'] != 'spms-edit-password-v1' or len(bytes.fromhex(value['salt'])) != 16 or len(bytes.fromhex(value['digest'])) != 64:
                raise ValueError()
            return value
        except (ValueError, KeyError, TypeError):
            raise APIError('編輯密碼設定異常，請聯絡管理人員', 503)

    def status(self):
        with self.lock:
            return dict(configured=self.settings() is not None, individual_accounts=False)

    def unlock(self, password):
        with self.lock:
            settings = self.settings()
            if settings is None:
                raise APIError('尚未設定編輯密碼，請聯絡管理人員', 403)
            now = time.monotonic()
            if now < self.blocked_until:
                raise APIError('密碼嘗試過多，請等候 30 秒再試', 429)
            if not isinstance(password, str) or not 1 <= len(password) <= 200 or not hmac.compare_digest(password_hash(password, bytes.fromhex(settings['salt'])), settings['digest']):
                self.failures += 1
                if self.failures >= 5:
                    self.blocked_until = now + 30
                    self.failures = 0
                raise APIError('編輯密碼不正確', 401)
            self.failures = 0
            self.sessions = {key: expires for key, expires in self.sessions.items() if expires > now}
            if len(self.sessions) >= 128:
                raise APIError('編輯視窗過多，請稍後再試或聯絡管理人員', 429)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now + 8 * 60 * 60
            return dict(token=token, expires_in=8 * 60 * 60)

    def require(self, token):
        with self.lock:
            self.settings()
            if not token or self.sessions.get(token, 0) <= time.monotonic():
                raise APIError('目前為唯讀模式，請輸入密碼開啟編輯', 401)

    def revoke(self, token):
        with self.lock:
            self.sessions.pop(token, None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, default=Path(__file__).resolve().parent / 'data/edit-password.json')
    args = parser.parse_args()
    try:
        print('設定／更換共用編輯密碼，不建立個人帳號。設定檔只存 salt 與 scrypt 雜湊。')
        password = getpass.getpass('新密碼：')
        if password != getpass.getpass('再次輸入：'):
            raise ValueError('兩次輸入不同，未修改設定')
        configure(args.file, password)
        print('已設定。既有編輯工作階段將失效；頁面重新整理後為唯讀。')
        return 0
    except (OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        print('未完成：', error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
