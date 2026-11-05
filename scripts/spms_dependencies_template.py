"""Offline Flask/Waitress installer for SPMS. Windows x64 CPython 3.13 only.

Run with the SPMS venv's Python; no Proxy, index or network download needed.
Does not replace the SPMS server, start a service or modify its data files.
"""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
import io

BUNDLE = {}  # BUILD_PAYLOAD


def validate_bundle():
    files, requirements = {}, []
    for name, item in BUNDLE.items():
        filename = item['filename']
        if Path(filename).name != filename or '/' in filename or '\\' in filename or not filename.endswith('.whl'):
            raise ValueError('Invalid wheel filename')
        raw = base64.b64decode(item['base64'], validate=True)
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Corrupt wheel: ' + filename)
        with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
            if wheel.testzip() is not None:
                raise ValueError('Wheel CRC failed: ' + filename)
        files[filename] = raw
        requirements.append(f"{name}=={item['version']} --hash=sha256:{item['sha256']}")
    if len(files) != 9:
        raise ValueError('Expected nine dependency wheels')
    return files, '\n'.join(requirements) + '\n'


def verify_environment():
    if sys.platform != 'win32' or sys.implementation.name != 'cpython' or sys.version_info[:2] != (3, 13):
        raise ValueError('Requires Windows CPython 3.13; do not use global Python or another platform.')
    if (struct.calcsize('P') != 8 or platform.machine().lower() not in ('amd64','x86_64')
            or 't' in getattr(sys,'abiflags','') or sysconfig.get_config_var('Py_GIL_DISABLED')):
        raise ValueError('Requires standard x64 CPython 3.13 (not ARM64, 32-bit or free-threaded).')
    expected = Path(__file__).resolve().parent / '.venv'
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != expected.resolve():
        raise ValueError('Place this file in the SPMS folder and run .\\.venv\\Scripts\\python.exe .\\install_spms_dependencies.py')
    import importlib.util
    if importlib.util.find_spec('pip') is None:
        raise ValueError('pip is missing from this venv; stop and report the error.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify environment and wheel hashes without installing')
    args = parser.parse_args(argv)
    try:
        files, requirements = validate_bundle()
        verify_environment()
        print('SPMS offline dependencies: Windows x64 CPython 3.13')
        print('Target environment:', sys.prefix)
        for name, item in BUNDLE.items():
            print(f"  {name}=={item['version']}")
        print('No network downloads. Existing dependency versions may be replaced; SPMS data/passwords are not touched.')
        print('This does NOT switch SPMS to Flask/Waitress. Stop SPMS before installing.')
        if args.check:
            print('CHECK ONLY: nothing installed.')
            return 0
        if input('Type INSTALL to install these packages into this venv: ') != 'INSTALL':
            print('Cancelled; nothing installed.')
            return 0
        with tempfile.TemporaryDirectory(prefix='spms-offline-dependencies-') as folder:
            directory = Path(folder)
            for filename, raw in files.items():
                (directory / filename).write_bytes(raw)
            locked = directory / 'requirements.txt'
            locked.write_text(requirements, encoding='utf-8')
            environment = os.environ.copy()
            # Avoid inherited pip configuration that could add index URLs,
            # target a global directory or alter the requested offline operation.
            for name in list(environment):
                if name.startswith('PIP_'):
                    del environment[name]
            environment['PIP_CONFIG_FILE'] = os.devnull
            command = [sys.executable, '-m', 'pip', '--isolated', '--disable-pip-version-check',
                       'install', '--no-index', '--no-cache-dir', '--only-binary=:all:',
                       '--find-links', str(directory), '--require-hashes', '-r', str(locked)]
            result = subprocess.run(command, env=environment)
            if result.returncode:
                print('Installation failed; packages may be partially changed. Keep the output; do not change Proxy/certificate policy.')
                return result.returncode
        verified = subprocess.run([sys.executable, '-c',
            "import flask, waitress; from importlib.metadata import version; print('Flask:', version('Flask')); print('Waitress:', version('waitress'))"])
        if verified.returncode:
            return verified.returncode
        print('Offline dependency installation completed. SPMS server code and data are unchanged.')
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print('DEPENDENCY INSTALL FAILED:', error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('Cancelled. If pip had started, check package status before retrying.')
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
