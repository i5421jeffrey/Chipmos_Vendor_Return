"""Temporary copies only. Flask tests skip when optional dependencies are absent."""
import base64
import concurrent.futures
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from database import connect
from edit_access import configure
from flask_server import create_app, prepare_test_copy
from server import initialize_database
from modules.repairs import service
from test_repairs import example

HAS_FLASK = importlib.util.find_spec('flask') is not None and importlib.util.find_spec('waitress') is not None


class CopyTests(unittest.TestCase):
    def test_snapshot_preserves_source_password_and_separates_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'spms.sqlite3'
            initialize_database(source)
            configure(source.parent/'edit-password.json','synthetic-only')
            service.save_record(source,example())
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            password=(source.parent/'edit-password.json').read_bytes()
            target,counts=prepare_test_copy(source)
            self.assertEqual(counts['repair_records'],1)
            self.assertNotEqual(target,source)
            self.assertEqual((target.parent/'edit-password.json').read_bytes(),password)
            service.save_record(target,example(serial_no='123456789'))
            self.assertEqual(service.list_records(source,{})['total'],1)
            self.assertEqual(service.list_records(target,{})['total'],2)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            another,_=prepare_test_copy(source)
            self.assertNotEqual(another,target)
            self.assertEqual(service.list_records(another,{})['total'],1)

    def test_missing_source_or_password_does_not_create_empty_database(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'missing.sqlite3'
            with self.assertRaises(ValueError): prepare_test_copy(source)
            self.assertFalse(source.exists())
            initialize_database(source)
            with self.assertRaises(ValueError): prepare_test_copy(source)
            self.assertFalse((source.parent/'flask-tests').exists())


@unittest.skipUnless(HAS_FLASK,'Optional Flask/Waitress packages not installed')
class FlaskTransportTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'spms.sqlite3'
        initialize_database(self.path)
        configure(self.path.parent/'edit-password.json','synthetic-only')
        self.log_file=self.path.parent/'connections.jsonl'
        self.app=create_app(self.path, diagnostic_log=self.log_file)
        self.app.config['TESTING']=True
        self.client=self.app.test_client()
        self.addCleanup(self.close_logs)

    def close_logs(self):
        for handler in self.app.extensions['spms_diagnostics'].handlers:
            handler.close()

    def call(self,path,method='GET',data=None,token=None,headers=None,source='10.1.121.40'):
        values={'X-SPMS-Request':'1'}
        if token: values['X-SPMS-Edit-Token']=token
        values.update(headers or {})
        return self.client.open(path,method=method,json=data,headers=values,
            base_url='http://10.1.121.135:8082',environ_overrides={'REMOTE_ADDR':source})

    def unlock(self):
        response=self.call('/api/edit/unlock','POST',{'password':'synthetic-only'})
        self.assertEqual(response.status_code,200,response.data)
        return response.json['token']

    def test_assets_reads_head_and_private_paths(self):
        for path in ('/','/repairs/','/repairs/app.js','/repairs/features.js','/repairs/style.css','/repairs/original.css','/repairs/parity.css','/repairs/ghost-logo.png'):
            response=self.call(path)
            self.assertEqual(response.status_code,200,path)
            self.assertTrue(response.data)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            head=self.call(path,'HEAD')
            self.assertEqual(head.data,b'')
            self.assertEqual(head.headers['Content-Length'],response.headers['Content-Length'])
        for path in ('/api/repairs/catalog','/api/repairs/dbn/catalog','/api/repairs/records','/api/repairs/dbn','/api/repairs/mappings','/api/repairs/history','/api/repairs/statistics','/api/repairs/masters','/api/modules'):
            self.assertEqual(self.call(path).status_code,200,path)
        for path in ('/data/spms.sqlite3','/flask_server.py','/static/../data/spms.sqlite3','/api/no-such-route'):
            self.assertEqual(self.call(path).status_code,404,path)

    def test_sources_host_forwarded_headers_and_origins_not_relaxed(self):
        for source in ('10.1.122.20','8.8.8.8','::1'):
            self.assertEqual(self.call('/api/health',source=source).status_code,403)
        self.assertEqual(self.call('/api/health',source='10.1.122.20',headers={'X-Forwarded-For':'10.1.121.40'}).status_code,403)
        self.assertEqual(self.call('/api/health',headers={'Host':'other.example:8082'}).status_code,403)
        for host in ('localhost:8082','127.0.0.1:8082','10.1.121.135:8082'):
            self.assertEqual(self.call('/api/health',headers={'Host':host}).status_code,200)
        for origin in ('http://evil.example','https://10.1.121.135:8082','null'):
            self.assertEqual(self.call('/api/edit/unlock','POST',{'password':'synthetic-only'},headers={'Origin':origin}).status_code,403)
        self.assertEqual(self.call('/api/edit/unlock','POST',{'password':'synthetic-only'},headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        log=self.log_file.read_text()
        self.assertIn('SOURCE_DENIED',log)
        self.assertIn('HOST_DENIED',log)
        self.assertIn('WRITE_REJECTED',log)
        self.assertNotIn('synthetic-only',log)

    def test_write_validation_conflict_lock_and_redacted_logs(self):
        self.assertEqual(self.call('/api/repairs/records','POST',example()).status_code,401)
        token=self.unlock()
        row=self.call('/api/repairs/records','POST',example(),token).json['data']
        response=self.call('/api/repairs/records/'+row['id'],'PUT',example(expected_version=1,failure_description='test edit'),token)
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(self.call('/api/repairs/records/'+row['id'],'PUT',example(expected_version=1),token).status_code,409)
        self.assertEqual(self.call('/api/repairs/records/'+row['id']+'/chain').status_code,200)
        self.assertEqual(self.call('/api/repairs/records/'+row['id']+'/history').status_code,200)
        self.call('/api/edit/lock','POST',{},token)
        self.assertEqual(self.call('/api/repairs/records/'+row['id'],'DELETE',{'expected_version':2},token).status_code,401)
        log=self.log_file.read_text()
        self.assertNotIn(token,log)
        self.assertNotIn('test edit',log)
        self.assertNotIn('synthetic-only',log)
        self.call('/api/health?password=DO_NOT_LOG_QUERY')
        self.assertNotIn('DO_NOT_LOG_QUERY',self.log_file.read_text())

    def test_bad_json_size_headers_and_unsupported_method(self):
        response=self.client.post('/api/repairs/records',base_url='http://127.0.0.1:8082',data='bad',content_type='application/json',headers={'X-SPMS-Request':'1'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.call('/api/repairs/records','POST',[],self.unlock()).status_code,400)
        self.assertEqual(self.call('/api/repairs/records','PATCH',{}).status_code,405)
        self.assertEqual(self.call('/api/repairs/records','OPTIONS').status_code,405)
        response=self.client.post('/api/repairs/records',base_url='http://127.0.0.1:8082',data='{}',content_type='text/plain',headers={'X-SPMS-Request':'1'})
        self.assertEqual(response.status_code,415)
        response=self.client.post('/api/repairs/records',base_url='http://127.0.0.1:8082',data='x'*(8*1024*1024),content_type='application/json',headers={'X-SPMS-Request':'1'})
        self.assertEqual(response.status_code,413)

    def test_attachment_bytes_and_deletion_share_existing_operations(self):
        token=self.unlock()
        row=self.call('/api/repairs/records','POST',example(),token).json['data']
        raw=b'original bytes\r\n<script>not html</script>'
        response=self.call('/api/repairs/records/'+row['id']+'/attachment','POST',
            dict(expected_version=1,attachment=dict(filename='log.asc',content_base64=base64.b64encode(raw).decode())),token)
        self.assertEqual(response.status_code,200,response.data)
        meta=self.call('/api/repairs/records/'+row['id']+'/attachment').json['data']
        self.assertEqual(self.call('/api/repairs/attachments/'+meta['id']).data,raw)
        response=self.call('/api/repairs/records/'+row['id'],'DELETE',{'expected_version':2},token)
        self.assertEqual(response.status_code,200,response.data)
        with connect(self.path) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM repair_attachments').fetchone()[0],0)

    def test_waitress_real_http_and_parallel_version_conflict(self):
        from waitress import create_server
        server=create_server(self.app,host='127.0.0.1',port=0,threads=10,clear_untrusted_proxy_headers=True)
        stopping=threading.Event()
        def run():
            try:
                server.run()
            except OSError:
                if not stopping.is_set(): raise
        thread=threading.Thread(target=run,daemon=True)
        thread.start()
        def cleanup():
            stopping.set()
            server.close()
            thread.join(5)
        self.addCleanup(cleanup)
        base=f'http://127.0.0.1:{server.effective_port}'
        token=self.unlock()
        row=self.call('/api/repairs/records','POST',example(),token).json['data']
        from urllib.error import HTTPError
        def update(index):
            request=Request(base+'/api/repairs/records/'+row['id'],method='PUT',data=json.dumps(example(expected_version=1,failure_description=str(index))).encode(),
                headers={'Host':'127.0.0.1:8082','Content-Type':'application/json','X-SPMS-Request':'1','X-SPMS-Edit-Token':token})
            try:
                with urlopen(request,timeout=10) as response: return response.status
            except HTTPError as error:
                with error: return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            statuses=list(pool.map(update,range(10)))
        self.assertEqual(sorted(statuses),[200]+[409]*9)


if __name__=='__main__':
    unittest.main()
