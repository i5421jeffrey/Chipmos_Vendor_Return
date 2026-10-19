"""Generate a reviewed SQL seed; preserve customer PIN spelling and ranges."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path


def parse_socket(text):
    declaration = re.search(r'^\s*DEFINE\s+MULTIPLE\s+(\d+)DUT\b', text, re.I | re.M)
    if not declaration:
        raise ValueError('Missing DEFINE MULTIPLE DUT count')
    count = int(declaration[1])
    pins = {}
    for number, line in enumerate(text.splitlines(), 1):
        # Inline comments (including "no DUT") do not remove the defined mapping.
        body = line.split(';', 1)[0]
        match = re.match(r'^\s*DUT\s*(\d+)\s*=\s*(.*)$', body, re.I)
        if not match:
            continue
        dut = str(int(match[1]))
        if dut in pins:
            raise ValueError(f'Duplicate DUT {dut} on line {number}')
        tokens = [token for token in re.split(r'[,\s]+', match[2].strip()) if token]
        if not tokens:
            raise ValueError(f'Empty PIN list on line {number}')
        for token in tokens:
            if not re.fullmatch(r'(?:PPS\d+(?:-\d+)?|PD?\d+(?:-\d+)?[A-H][1-8])', token, re.I):
                raise ValueError(f'Unrecognized token on line {number}: {token}')
        # Do not uppercase, rename PD/P, expand ranges, merge, or deduplicate.
        pins[dut] = tokens
    if set(pins) != {str(n) for n in range(1, count + 1)}:
        raise ValueError('DUT rows must exactly match the declared DUT count')
    return count, pins


def build_seed(source, product):
    raw = source.read_bytes()
    # Legacy files may contain non-UTF-8 comments. Parse ASCII syntax without
    # guessing their encoding; preserve every original byte in source_bytes.
    # Non-ASCII PIN tokens still fail validation rather than being replaced.
    text = raw.decode('utf-8-sig', errors='surrogateescape')
    count, pins = parse_socket(text)
    digest = hashlib.sha256(raw).hexdigest()
    literal = lambda value: "'" + value.replace("'", "''") + "'"
    encoded = base64.b64encode(raw).decode('ascii')
    mapping = json.dumps(pins, ensure_ascii=False, separators=(',', ':'))
    return f"""-- Generated from {source.name}; original file bytes are preserved as base64.
-- Product binding {product} was supplied by the user, not inferred from the header.
-- Run after dbn_dut_socket_migration.sql. No existing DBN snapshots are rewritten.
begin;
update public.dbn_socket_files set is_active = false
where product_code = {literal(product)} and id <> {literal(digest)};
insert into public.dbn_socket_files
  (id, product_code, source_filename, source_bytes, dut_count, dut_pins, is_active)
values (
  {literal(digest)}, {literal(product)}, {literal(source.name)},
  decode('{encoded}', 'base64'),
  {count}, $socket_json${mapping}$socket_json$::jsonb, true
)
on conflict (product_code, id) do update set is_active = true;
notify pgrst, 'reload schema';
commit;
"""


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('product')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(build_seed(args.source, args.product), encoding='utf-8')
    print(f'Generated {args.output}')
