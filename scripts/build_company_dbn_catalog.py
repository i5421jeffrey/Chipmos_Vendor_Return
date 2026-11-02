"""Extract reviewed DBN reference data from repository SQL, never a live service."""
import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    paths = [ROOT / 'supabase' / name for name in (
        'dbn_records_migration.sql', 'dbn_qr_products_20261029_migration.sql',
        'dbn_socket_jaa118_seed.sql', 'dbn_socket_gaa112_20261019_seed.sql',
        'dbn_socket_caa100_20261020_seed.sql', 'dbn_socket_gaa126_20261029_seed.sql')]
    original = paths[0].read_text()
    combinations = set(re.findall(r"\('(AB)', '([^']+)', '([^']+)'\)", original))
    qr = paths[1].read_text()
    products = re.findall(r"\('([^']+)'\)", qr.split('from (values', 1)[1].split('as products', 1)[0])
    stations = re.findall(r"\('([^']+)'\)", qr.split('cross join (values', 1)[1].split('as stations', 1)[0])
    combinations.update(('QR', product, station) for product in products for station in stations)
    sockets = []
    for path in paths[2:]:
        text = path.read_text()
        match = re.search(r"values \(\s*'([^']+)', '([^']+)', '([^']+)',\s*decode\('([^']+)', 'base64'\),\s*(\d+), \$socket_json\$(.*?)\$socket_json\$", text, re.S)
        if not match:
            raise ValueError(f'Unrecognized Socket seed: {path}')
        identity, product, filename, source, count, pins = match.groups()
        if hashlib.sha256(base64.b64decode(source, validate=True)).hexdigest() != identity:
            raise ValueError(f'Socket source hash mismatch: {path}')
        sockets.append(dict(id=identity, product_code=product, source_filename=filename,
                            dut_count=int(count), dut_pins=json.loads(pins)))
    return {'sources': [{'file': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
            'customers': ['AB', 'QR', 'VB'],
            'combinations': [dict(zip(('customer_code', 'product_code', 'station_code'), row)) for row in sorted(combinations)],
            'sockets': sockets}


if __name__ == '__main__':
    target = ROOT / 'company/modules/repairs/dbn_catalog.json'
    target.write_text(json.dumps(build(), ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(target)
