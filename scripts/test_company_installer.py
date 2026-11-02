import hashlib
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from build_company_installer import FILES, ROOT, build


class InstallerTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name).resolve()
        self.code = build()
        self.module = types.ModuleType("installer_test")
        self.module.__file__ = str(self.base / "install_spms.py")
        exec(compile(self.code, self.module.__file__, "exec"), self.module.__dict__)

    def seed_old_files(self):
        for relative, content in {
            "company/server.py": b"old program\r\n",
            "company/data/spms.sqlite3": b"existing database; never open or overwrite",
            "company/data/spms.sqlite3-wal": b"existing WAL",
            ".venv/keep.txt": b"existing venv",
            "company/unlisted.txt": b"user work",
        }.items():
            target = self.base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def assert_protected(self):
        self.assertEqual((self.base / "company/data/spms.sqlite3").read_bytes(), b"existing database; never open or overwrite")
        self.assertEqual((self.base / "company/data/spms.sqlite3-wal").read_bytes(), b"existing WAL")
        self.assertEqual((self.base / ".venv/keep.txt").read_bytes(), b"existing venv")
        self.assertEqual((self.base / "company/unlisted.txt").read_bytes(), b"user work")

    def test_generated_payload_exactly_matches_sources(self):
        self.assertEqual((ROOT / "install_spms.py").read_bytes(), self.code.encode())
        contents = self.module.validate_bundle(self.base)
        self.assertEqual(set(contents), {"company/" + name for name in FILES})
        for name, content in contents.items():
            self.assertEqual(content, (ROOT / name).read_text(encoding="utf-8").encode())
            self.assertEqual(hashlib.sha256(content).hexdigest(), self.module.BUNDLE["files"][name]["sha256"])

    def test_preview_and_cancellation_do_not_write(self):
        script = self.base / "install_spms.py"
        script.write_text(self.code, encoding="utf-8")
        for args, answer, expected in ((["--check"], "", "CHECK OK"), ([], "NO\n", "Cancelled")):
            completed = subprocess.run([sys.executable, str(script), *args], input=answer,
                                       text=True, capture_output=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(expected, completed.stdout)
            self.assertEqual(list(self.base.iterdir()), [script])

    def test_install_preserves_database_venv_and_backups_program(self):
        self.seed_old_files()
        backup = self.module.install(self.base)
        self.assert_protected()
        self.assertEqual((backup / "company/server.py").read_bytes(), b"old program\r\n")
        self.assertFalse((backup / "company/data").exists())
        for name, entry in self.module.BUNDLE["files"].items():
            self.assertEqual((self.base / name).read_bytes(), entry["content"].encode())
        self.assertFalse((self.base / ".spms-install.lock").exists())
        self.assertEqual(list(self.base.glob(".spms-stage-*")), [])

    def test_install_failure_rolls_back_program(self):
        self.seed_old_files()
        original = self.module.replace_program
        count = 0
        def failing_replace(source, target):
            nonlocal count
            count += 1
            if count == 10:
                raise PermissionError("simulated locked file")
            original(source, target)
        with patch.object(self.module, "replace_program", failing_replace):
            with self.assertRaises(PermissionError):
                self.module.install(self.base)
        self.assertEqual((self.base / "company/server.py").read_bytes(), b"old program\r\n")
        self.assertFalse((self.base / "company/database.py").exists())
        self.assert_protected()
        self.assertFalse((self.base / ".spms-install.lock").exists())

    def test_existing_install_lock_is_not_removed(self):
        lock = self.base / ".spms-install.lock"
        lock.write_text("other installer")
        with self.assertRaises(FileExistsError):
            self.module.install(self.base)
        self.assertEqual(lock.read_text(), "other installer")

    def test_corrupt_content_fails_before_changes(self):
        self.module.BUNDLE["files"]["company/server.py"]["content"] += "corruption"
        with self.assertRaises(ValueError):
            self.module.install(self.base)
        self.assertEqual(list(self.base.iterdir()), [])

    def test_protected_and_traversal_paths_rejected(self):
        entry = self.module.BUNDLE["files"]["company/server.py"]
        for name in ("company/data/spms.sqlite3", "company/DATA/file.py", ".venv/file.py", "company/../file.py",
                     "/company/file.py", "company\\server.py", "company/file.py:stream", "company/.hidden.py"):
            self.module.BUNDLE["files"][name] = entry
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.validate_bundle(self.base)
            del self.module.BUNDLE["files"][name]
        self.assertEqual(list(self.base.iterdir()), [])

    def test_symlink_target_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.base / "company").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.module.install(self.base)
        self.assertEqual(list(outside.iterdir()), [])

    def test_single_file_cli_installs_without_source_tree(self):
        script = self.base / "install_spms.py"
        script.write_text(self.code, encoding="utf-8")
        completed = subprocess.run([sys.executable, str(script)], input="INSTALL\n",
                                   text=True, capture_output=True, timeout=20, cwd=self.base)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("INSTALL OK", completed.stdout)
        self.assertFalse((self.base / "company/data").exists())
        # Run all packaged service tests without a repository or network access.
        tests = subprocess.run([sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover",
                                "-s", "company", "-p", "test_*.py"], cwd=self.base,
                               text=True, capture_output=True, timeout=60)
        self.assertEqual(tests.returncode, 0, tests.stderr)


if __name__ == "__main__":
    unittest.main()
