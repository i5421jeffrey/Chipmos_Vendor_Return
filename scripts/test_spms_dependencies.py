import base64
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from build_spms_dependencies import ROOT, PACKAGES, build, bundle


class OfflineDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.code = build()
        self.module = types.ModuleType('offline_dependency_test')
        self.module.__file__ = str(ROOT / 'install_spms_dependencies.py')
        exec(compile(self.code, self.module.__file__, 'exec'), self.module.__dict__)

    def test_generated_file_matches_sources_and_only_wheels_packaged(self):
        self.assertEqual((ROOT/'install_spms_dependencies.py').read_bytes(), self.code.encode())
        self.assertEqual(set(self.module.BUNDLE), set(PACKAGES))
        files, locked = self.module.validate_bundle()
        self.assertEqual(len(files),9)
        self.assertEqual(len(locked.splitlines()),9)
        for name, item in self.module.BUNDLE.items():
            self.assertEqual(item['version'], PACKAGES[name])
            raw = files[item['filename']]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
            with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
                self.assertIsNone(wheel.testzip())
                self.assertTrue(any('.dist-info/' in path and ('license' in path.lower() or 'copying' in path.lower()) for path in wheel.namelist()))
        self.assertNotIn('http://',locked)
        self.assertNotIn('https://',locked)

    def test_corruption_and_unsafe_filename_fail_before_install(self):
        item = self.module.BUNDLE['flask']
        item['base64'] = base64.b64encode(b'bad wheel').decode()
        with patch.object(self.module.subprocess,'run') as run, patch('builtins.input') as prompt, patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(self.module.main([]),1)
            run.assert_not_called()
            prompt.assert_not_called()
        item['filename'] = '../outside.whl'
        with self.assertRaises(ValueError): self.module.validate_bundle()

    def test_environment_guard_rejects_wrong_os_or_global_python(self):
        with patch.object(self.module.sys,'platform','darwin'), self.assertRaises(ValueError):
            self.module.verify_environment()
        with patch.object(self.module.sys,'platform','win32'), patch.object(self.module.sys,'version_info',(3,13)), \
             patch.object(self.module.platform,'machine',return_value='AMD64'), patch.object(self.module.struct,'calcsize',return_value=8), \
             patch.object(self.module.sysconfig,'get_config_var',return_value=0), \
             patch.object(self.module.sys,'prefix','global'), patch.object(self.module.sys,'base_prefix','global'), self.assertRaises(ValueError):
            self.module.verify_environment()

    def test_check_and_cancel_never_run_pip(self):
        for args, answer in ((['--check'],'INSTALL'),([], 'NO')):
            with self.subTest(args=args), patch.object(self.module,'verify_environment'), \
                 patch.object(self.module.subprocess,'run') as run, patch('builtins.input',return_value=answer), patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(self.module.main(args),0)
                run.assert_not_called()

    def test_install_uses_offline_hashed_wheels_and_current_python(self):
        calls=[]
        def run(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[0],sys.executable)
            if len(calls)==1:
                for flag in ('--no-index','--isolated','--no-cache-dir','--require-hashes','--only-binary=:all:'):
                    self.assertIn(flag,command)
                wheel_dir=Path(command[command.index('--find-links')+1])
                self.assertEqual(len(list(wheel_dir.glob('*.whl'))),9)
                locked=Path(command[-1]).read_text()
                self.assertEqual(locked.count('--hash=sha256:'),9)
                self.assertNotIn('PIP_TARGET',kwargs['env'])
                self.assertNotIn('PIP_INDEX_URL',kwargs['env'])
            return subprocess.CompletedProcess(command,0)
        with patch.object(self.module,'verify_environment'), patch.object(self.module.subprocess,'run',side_effect=run), \
             patch.dict(self.module.os.environ,{'PIP_TARGET':'wrong-folder','PIP_INDEX_URL':'https://invalid.example'}), \
             patch('builtins.input',return_value='INSTALL'),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(self.module.main([]),0)
        self.assertEqual(len(calls),2)

    def test_pip_failure_is_reported_without_retry_or_false_success(self):
        with patch.object(self.module,'verify_environment'), patch.object(self.module.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as run, \
             patch('builtins.input',return_value='INSTALL'), patch('sys.stdout',new=io.StringIO()) as output:
            self.assertEqual(self.module.main([]),1)
            self.assertIn('partially changed',output.getvalue())
            self.assertNotIn('installation completed',output.getvalue())
            self.assertEqual(run.call_count,1)

    def test_windows_cp313_dependencies_resolve_without_network(self):
        # Download to a temporary directory from local wheels only. No install.
        with tempfile.TemporaryDirectory() as folder:
            _, locked = self.module.validate_bundle()
            requirements=Path(folder)/'requirements.txt'
            requirements.write_text(locked)
            result=subprocess.run([sys.executable,'-m','pip','--isolated','--disable-pip-version-check',
                'download','--no-index','--no-cache-dir','--find-links',str(ROOT/'company/offline_wheels'),
                '--only-binary=:all:','--platform','win_amd64','--python-version','3.13','--implementation','cp','--abi','cp313',
                '--require-hashes','-r',str(requirements),'--dest',folder],text=True,capture_output=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(len(list(Path(folder).glob('*.whl'))),9)


if __name__ == '__main__':
    unittest.main()
