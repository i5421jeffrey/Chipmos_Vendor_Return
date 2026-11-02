import base64
import hashlib
import json
import unittest

from build_company_ui_assets import ROOT, build


class OriginalAssetsTests(unittest.TestCase):
    def test_assets_are_reproducible_and_logo_bytes_match(self):
        for filename, content in build().items():
            self.assertEqual((ROOT / 'company/web' / filename).read_bytes(), content.encode('utf-8'))
        branding = json.loads(build()['branding.json'])
        logo = base64.b64decode(branding['content_base64'], validate=True)
        self.assertEqual(logo, (ROOT / branding['source']).read_bytes())
        self.assertEqual(hashlib.sha256(logo).hexdigest(), branding['sha256'])
        self.assertNotIn('adminPassword', build()['original.css'])


if __name__ == '__main__':
    unittest.main()
