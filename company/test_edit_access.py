import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from edit_access import EditGate, configure
from errors import APIError
import test_server as basic
from test_repairs import example


class EditGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'edit-password.json'
        self.gate = EditGate(self.path)

    def test_unconfigured_is_readonly_and_hash_only_config(self):
        self.assertFalse(self.gate.status()['configured'])
        with self.assertRaises(APIError):
            self.gate.unlock('test')
        configure(self.path, 'shared-test-password')
        self.assertNotIn('shared-test-password', self.path.read_text())
        self.assertTrue(self.gate.status()['configured'])

    def test_bad_password_expiry_revoke_and_restart(self):
        configure(self.path, 'shared-test-password')
        with self.assertRaises(APIError):
            self.gate.unlock('wrong')
        token = self.gate.unlock('shared-test-password')['token']
        self.gate.require(token)
        self.gate.revoke(token)
        with self.assertRaises(APIError):
            self.gate.require(token)
        token = self.gate.unlock('shared-test-password')['token']
        with self.assertRaises(APIError):
            EditGate(self.path).require(token)
        with patch('edit_access.time.monotonic', return_value=time.monotonic() + 9 * 3600):
            with self.assertRaises(APIError):
                self.gate.require(token)

    def test_password_rotation_and_corruption_fail_closed(self):
        configure(self.path, 'old')
        token = self.gate.unlock('old')['token']
        configure(self.path, 'new')
        with self.assertRaises(APIError):
            self.gate.require(token)
        self.path.write_text('{bad')
        with self.assertRaises(APIError):
            self.gate.unlock('new')

    def test_attempt_cooldown(self):
        configure(self.path, 'test')
        for _ in range(5):
            with self.assertRaises(APIError):
                self.gate.unlock('wrong')
        with self.assertRaises(APIError) as caught:
            self.gate.unlock('test')
        self.assertEqual(caught.exception.status, 429)
        with patch('edit_access.time.monotonic', return_value=time.monotonic() + 31):
            self.gate.require(self.gate.unlock('test')['token'])


class EditHTTPTests(unittest.TestCase):
    setUp = basic.LocalServiceTests.setUp

    def request(self, path, method='GET', payload=None, token=None, headers=None):
        values = {'Content-Type':'application/json', 'X-SPMS-Request':'1'}
        if token:
            values['X-SPMS-Edit-Token'] = token
        values.update(headers or {})
        body = json.dumps(payload).encode() if payload is not None else None
        with urlopen(Request(self.base + path, data=body, method=method, headers=values), timeout=5) as response:
            return json.load(response)

    def test_all_mutations_denied_without_token_but_reads_work(self):
        self.assertFalse(self.request('/api/edit/status')['configured'])
        self.assertEqual(self.request('/api/repairs/records')['total'], 0)
        endpoints = [('/api/repairs/records','POST'),('/api/repairs/records/test','PUT'),
                     ('/api/repairs/records/test','DELETE'),('/api/repairs/dbn','POST'),('/api/repairs/dbn/test','PUT'),
                     ('/api/repairs/dbn/test','DELETE'),('/api/repairs/records/test/resolve','POST'),
                     ('/api/repairs/records/test/attachment','POST'),('/api/repairs/attachments/test','DELETE'),
                     ('/api/repairs/mappings','POST'),('/api/repairs/masters','POST')]
        for path, method in endpoints:
            with self.subTest(path=path, method=method), self.assertRaises(HTTPError) as caught:
                self.request(path, method, {})
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()

    def test_unlock_write_lock_and_config_not_served(self):
        configure(self.database.parent / 'edit-password.json', 'http-test')
        with self.assertRaises(HTTPError) as caught:
            self.request('/api/edit/unlock','POST',{'password':'http-test'},headers={'Origin':'http://evil.example'})
        self.assertEqual(caught.exception.code,403)
        caught.exception.close()
        token = self.request('/api/edit/unlock','POST',{'password':'http-test'})['token']
        self.assertTrue(self.request('/api/repairs/records','POST',example(),token)['data'])
        self.request('/api/edit/lock','POST',{},token)
        for value in (token, 'forged'):
            with self.assertRaises(HTTPError) as caught:
                self.request('/api/repairs/records','POST',example(),value)
            self.assertEqual(caught.exception.code,401)
            caught.exception.close()
        with self.assertRaises(HTTPError) as caught:
            self.request('/data/edit-password.json')
        self.assertEqual(caught.exception.code,404)
        caught.exception.close()
        self.assertNotIn('digest', self.request('/api/edit/status'))
