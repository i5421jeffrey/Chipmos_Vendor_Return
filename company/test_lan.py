"""Loopback network simulations, not a Windows LAN/firewall acceptance test."""
import concurrent.futures
import contextlib
import io
import json
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from edit_access import configure
from server import LocalServer, bind_address, client_network, initialize_database, startup_options
from modules.repairs import service
from test_repairs import example


class LANOptionsTests(unittest.TestCase):
    def test_approved_default_and_explicit_lan(self):
        default = startup_options([])
        self.assertEqual(default.host, '10.1.121.61')
        self.assertEqual(list(map(str, default.client_subnet)), ['10.1.121.0/24'])
        self.assertTrue(default.lan)
        self.assertTrue(default.allow_http_lan)
        local = startup_options(['--host','127.0.0.1'])
        self.assertFalse(local.lan)
        self.assertFalse(local.allow_http_lan)
        self.assertEqual(local.client_subnet, [])
        secure = startup_options(['--tls-cert','cert.pem','--tls-key','key.pem'])
        self.assertEqual(secure.host, default.host)
        self.assertFalse(secure.allow_http_lan)
        args = startup_options(['--host','192.168.10.20','--client-subnet','192.168.10.0/24','--allow-http-lan'])
        self.assertTrue(args.lan)
        self.assertEqual(str(args.client_subnet[0]), '192.168.10.0/24')

    def test_reject_unsafe_or_incomplete_options(self):
        cases = [ ['--host','0.0.0.0'], ['--host','8.8.8.8'], ['--host','localhost'],
                  ['--host','192.168.1.2'], ['--host','192.168.1.2','--client-subnet','192.168.1.0/24'],
                  ['--client-subnet','0.0.0.0/0'], ['--client-subnet','192.168.1.2/24'],
                  ['--tls-cert','cert.pem'], ['--port','0'] ]
        for values in cases:
            with self.subTest(values=values), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                startup_options(values)
        args = startup_options(['--host','10.1.1.20','--client-subnet','10.1.1.0/24','--tls-cert','cert.pem','--tls-key','key.pem'])
        self.assertTrue(args.lan)

    def test_server_constructor_requires_specific_bind_and_allowlist(self):
        for host in ('0.0.0.0','8.8.8.8','192.168.1.10'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                LocalServer((host,0),Path('unused.sqlite3'))


class LANHTTPTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.database = self.root / 'spms.sqlite3'
        initialize_database(self.database)
        configure(self.root / 'edit-password.json','test-only')

    def start(self, context=None):
        server = LocalServer(('127.0.0.1',0), self.database, [client_network('192.168.10.0/24')], context)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join,5)
        self.addCleanup(server.shutdown)
        return server

    def request(self, server, path, method='GET', body=None, headers=None, context=None):
        defaults = {'X-SPMS-Request':'1','Content-Type':'application/json'}
        defaults.update(headers or {})
        url = f'{server.scheme}://127.0.0.1:{server.server_port}{path}'
        request = Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=defaults)
        try:
            with urlopen(request,timeout=10,context=context) as response:
                return response.status,json.load(response)
        except HTTPError as error:
            with error:
                return error.code,json.load(error)

    def test_client_filter_and_host_origin_pairing(self):
        server = self.start()
        self.assertTrue(server.verify_request(None,('192.168.10.45',1234)))
        self.assertFalse(server.verify_request(None,('192.168.11.45',1234)))
        self.assertFalse(server.verify_request(None,('8.8.8.8',1234)))
        self.assertFalse(server.verify_request(None,('::1',1234)))
        # Simulate the exact Host a private-address listener will accept.
        lan_host = f'192.168.10.20:{server.server_port}'
        server.allowed_hosts = {lan_host}
        self.assertEqual(self.request(server,'/api/health',headers={'Host':lan_host})[0],200)
        server.lan = True
        self.assertEqual(self.request(server,'/api/health',headers={'Host':lan_host})[1]['access'],'lan-allowlist')
        self.assertEqual(self.request(server,'/api/health',headers={'Host':'attacker.example'})[0],403)
        for origin in ('http://attacker.example', 'null', 'https://'+lan_host, 'http://localhost:'+str(server.server_port)):
            status,_ = self.request(server,'/api/edit/unlock','POST',{'password':'test-only'}, {'Host':lan_host,'Origin':origin})
            self.assertEqual(status,403)
        status,data = self.request(server,'/api/edit/unlock','POST',{'password':'test-only'}, {'Host':lan_host,'Origin':'http://'+lan_host})
        self.assertEqual(status,200)
        self.assertTrue(data['token'])
        self.assertEqual(self.request(server,'/api/edit/unlock','POST',{'password':'test-only'}, {'Host':lan_host,'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_ten_clients_keep_sessions_and_record_conflicts_isolated(self):
        server = self.start()
        row = service.save_record(self.database,example())['data']
        barrier = threading.Barrier(10)
        def edit(index):
            status,data = self.request(server,'/api/edit/unlock','POST',{'password':'test-only'})
            self.assertEqual(status,200)
            token = data['token']
            barrier.wait(timeout=15)
            status,_ = self.request(server,'/api/repairs/records/'+row['id'],'PUT',
                example(expected_version=1,failure_description=f'client {index}'),{'X-SPMS-Edit-Token':token})
            return token,status
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(edit, range(10)))
        self.assertEqual(len({token for token,_ in results}),10)
        self.assertEqual(sorted(status for _,status in results),[200]+[409]*9)
        self.assertEqual(service.record_detail(self.database,row['id'])['data']['version'],2)
        self.request(server,'/api/edit/lock','POST',{}, {'X-SPMS-Edit-Token':results[0][0]})
        server.edit_gate.require(results[1][0])
        status,_ = self.request(server,'/api/repairs/records','POST',example())
        self.assertEqual(status,401)

    @unittest.skipUnless(shutil.which('openssl'), 'OpenSSL CLI required for temporary test certificate')
    def test_tls_transport_origin_and_certificate_validation(self):
        cert,key = self.root/'cert.pem',self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-keyout',str(key),'-out',str(cert),'-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],
            check=True,capture_output=True,timeout=30)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert,key)
        server = self.start(context)
        client = ssl.create_default_context(cafile=str(cert))
        self.assertEqual(self.request(server,'/api/health',context=client)[1]['transport'],'https')
        origin = f'https://127.0.0.1:{server.server_port}'
        self.assertEqual(self.request(server,'/api/edit/unlock','POST',{'password':'test-only'},{'Origin':origin},client)[0],200)
        self.assertEqual(self.request(server,'/api/edit/unlock','POST',{'password':'test-only'},{'Origin':origin.replace('https:','http:')},client)[0],403)


if __name__ == '__main__':
    unittest.main()
