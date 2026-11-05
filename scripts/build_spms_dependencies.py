"""Build a single-file offline dependency installer; never include SPMS data.

--verify-pypi compares the downloaded wheels against PyPI's published SHA256.
The generated installer never accesses PyPI or any other package index.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import pprint
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WHEELS = ROOT / 'company/offline_wheels'
PACKAGES = {'flask':'3.1.3', 'waitress':'3.0.2', 'blinker':'1.9.0', 'click':'8.5.0',
            'colorama':'0.4.6', 'itsdangerous':'2.2.0', 'jinja2':'3.1.6',
            'markupsafe':'3.0.4', 'werkzeug':'3.1.9'}


def bundle(verify_pypi=False):
    result = {}
    for path in sorted(WHEELS.glob('*.whl')):
        name, version = path.name.split('-')[:2]
        if name not in PACKAGES or PACKAGES[name] != version or name in result:
            raise ValueError('Unexpected or duplicate wheel: ' + path.name)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(io.BytesIO(raw)) as wheel:
            if wheel.testzip() is not None:
                raise ValueError('Wheel CRC failed: ' + path.name)
        if verify_pypi:
            with urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
                releases = json.load(response)['urls']
            matches = [item for item in releases if item['filename'] == path.name]
            if len(matches) != 1 or matches[0]['digests']['sha256'] != digest:
                raise ValueError('PyPI SHA256 mismatch: ' + path.name)
            print('PyPI SHA256 verified:', path.name)
        result[name] = dict(filename=path.name, version=version, sha256=digest,
                            base64=base64.b64encode(raw).decode('ascii'))
    if set(result) != set(PACKAGES):
        raise ValueError('Missing offline dependency wheels')
    return result


def build(verify_pypi=False):
    template = (ROOT / 'scripts/spms_dependencies_template.py').read_text(encoding='utf-8')
    return template.replace('BUNDLE = {}  # BUILD_PAYLOAD',
                            'BUNDLE = ' + pprint.pformat(bundle(verify_pypi), width=110, sort_dicts=True), 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-pypi', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'install_spms_dependencies.py'
    output.write_bytes(build(args.verify_pypi).encode('utf-8'))
    print(f'Built {output.name}: {output.stat().st_size} bytes')
