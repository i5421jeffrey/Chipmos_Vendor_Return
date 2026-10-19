import base64
import json
import re
import tempfile
import unittest
from pathlib import Path

from build_socket_seed import build_seed, parse_socket


class SocketSeedTests(unittest.TestCase):
    def test_preserves_original_tokens_and_no_dut(self):
        count, pins = parse_socket('DEFINE MULTIPLE 2DUT 1STN\nDUT1 = PPS137,PD1-7C1,PD49C1,PD31C1\nDUT2 = pd51A7,P51A7 ; no DUT')
        self.assertEqual(count, 2)
        self.assertEqual(pins['1'], ['PPS137', 'PD1-7C1', 'PD49C1', 'PD31C1'])
        self.assertEqual(pins['2'], ['pd51A7', 'P51A7'])

    def test_rejects_missing_duplicate_and_bad_tokens(self):
        for body in ['DUT1=PPS1', 'DUT1=PPS1\nDUT1=PPS2', 'DUT1=BAD\nDUT2=PPS2']:
            with self.assertRaises(ValueError):
                parse_socket('DEFINE MULTIPLE 2DUT 1STN\n' + body)

    def test_whitespace_and_mixed_separators(self):
        count, pins = parse_socket('DEFINE MULTIPLE 2DUT 1STN\nDUT1\t=PPS137\tPD1C1  P33C1\nDUT2= PPS138, pd51A7\tP51A7 ; no DUT')
        self.assertEqual(count, 2)
        self.assertEqual(pins['1'], ['PPS137', 'PD1C1', 'P33C1'])
        self.assertEqual(pins['2'], ['PPS138', 'pd51A7', 'P51A7'])

    def test_legacy_comment_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'socket.asc'
            raw = b'; legacy \xff\xfe\r\nDEFINE MULTIPLE 1DUT 1STN\r\nDUT1=PPS137\tPD1C1 P33C1 ; no DUT\r\n'
            source.write_bytes(raw)
            seed = build_seed(source, 'GAA112')
            self.assertEqual(base64.b64decode(re.search(r"decode\('([^']+)'", seed)[1]), raw)
            self.assertEqual(json.loads(seed.split('$socket_json$')[1])['1'], ['PPS137', 'PD1C1', 'P33C1'])
            source.write_bytes(b'DEFINE MULTIPLE 1DUT 1STN\nDUT1=PD1C1\xff')
            with self.assertRaises(ValueError):
                build_seed(source, 'GAA112')

    def test_seed_round_trips_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'socket.txt'
            raw = b'\xef\xbb\xbfDEFINE MULTIPLE 1DUT 1STN\r\nDUT1 = PD49C1,PD31C1\r\n'
            source.write_bytes(raw)
            seed = build_seed(source, 'JAA118')
            self.assertEqual(base64.b64decode(re.search(r"decode\('([^']+)'", seed)[1]), raw)
            mapping = json.loads(seed.split('$socket_json$')[1])
            self.assertEqual(mapping['1'], ['PD49C1', 'PD31C1'])


if __name__ == '__main__':
    unittest.main()
