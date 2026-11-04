import base64
import ast
import hashlib
import json
from html.parser import HTMLParser
import unittest

from build_company_ui_assets import ROOT, build


class OriginalAssetsTests(unittest.TestCase):
    def test_everyday_pages_use_spms_brand_without_deployment_labels(self):
        for name in ('index.html','repairs.html','app.js','repairs.js','features.js'):
            content = (ROOT / 'company/web' / name).read_text(encoding='utf-8')
            self.assertNotRegex(content, r'本機|離線|驗收|公司版|移植|[Ss]upabase|SQLite|Python|來源歷史|匯入當時')
            if name.endswith('.html'):
                self.assertIn('<title>SPMS</title>', content)
        home = (ROOT / 'company/web/index.html').read_text(encoding='utf-8')
        self.assertIn('<h1>SPMS</h1>', home)
        self.assertIn('<a href="/repairs/">進入備品管理</a>', home)
        self.assertNotIn('<aside', home)
        self.assertNotIn('<dl', home)
        repairs = (ROOT / 'company/web/repairs.html').read_text(encoding='utf-8')
        self.assertNotIn('class="local-information"', repairs)
        self.assertIn('value="IMPORT">資料建立', repairs)

    def test_runtime_pages_only_use_packaged_local_assets_and_keep_master_navigation(self):
        class Page(HTMLParser):
            def __init__(self):
                super().__init__()
                self.assets, self.masters = [], []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag in ('script', 'img') and attrs.get('src'):
                    self.assets.append(attrs['src'])
                if tag == 'link' and attrs.get('href'):
                    self.assets.append(attrs['href'])
                if attrs.get('data-workspace') == 'masters':
                    self.masters.append(attrs)

        tree = ast.parse((ROOT / 'company/server.py').read_text(encoding='utf-8'))
        routes = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ASSETS' for target in node.targets))
        for name in ('index.html', 'repairs.html'):
            page = Page()
            page.feed((ROOT / 'company/web' / name).read_text(encoding='utf-8'))
            for asset in page.assets:
                self.assertTrue(asset.startswith('/') and not asset.startswith('//'), asset)
                if asset != '/repairs/ghost-logo.png':
                    self.assertIn(asset, routes)
                    self.assertTrue((ROOT / 'company/web' / routes[asset][0]).is_file())
            if name == 'repairs.html':
                self.assertEqual(len(page.masters), 1)
                self.assertNotIn('disabled', page.masters[0])
                self.assertNotIn('hidden', page.masters[0])
        for name in ('app.js', 'repairs.js', 'features.js'):
            script = (ROOT / 'company/web' / name).read_text(encoding='utf-8')
            self.assertNotRegex(script.replace('http://www.w3.org/2000/svg', ''), r'https?://')
            self.assertNotIn('innerHTML', script)

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
