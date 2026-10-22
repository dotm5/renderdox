"""Keep public capability summaries aligned with their runtime registries."""
import importlib.util
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]


class DocumentationTests(unittest.TestCase):
    def test_current_mcp_count_matches_catalog(self):
        sys.path.insert(0, str(ROOT / 'tools/renderdoc-mcp'))
        try:
            from contracts import VERSION
            from contracts.catalog import TOOLS
        finally:
            sys.path.pop(0)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        count = re.search(r'\| MCP capture and replay \| (\d+) tools', readme)
        self.assertIsNotNone(count)
        self.assertEqual(int(count.group(1)), len(TOOLS))
        current = (ROOT / 'docs/current-status.md').read_text(encoding='utf-8')
        self.assertIn('%s，%d 个工具' % (VERSION, len(TOOLS)), current)

    def test_proxy_profiles_match_current_reference(self):
        spec = importlib.util.spec_from_file_location('documented_routes', ROOT / 'tools/proxy-builder/routes.py')
        routes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(routes)
        readme = (ROOT / 'tools/proxy-builder/README.md').read_text(encoding='utf-8')
        documented = set(re.findall(r'^\| ([a-z]+) \|', readme, re.M))
        self.assertEqual(documented, set(routes.PROFILES))

    def test_deployment_subset_uses_current_packaged_aftermath(self):
        spec = importlib.util.spec_from_file_location('documented_subset', ROOT / 'util/buildscripts/check_windows_deployment_subset.py')
        subset = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(subset)
        self.assertEqual(subset.SUBSETS['aftermath'], [
            'bootstrap/aftermath_proxy/GFSDK_Aftermath_Lib.x64.dll', 'dgcore.dll'])


if __name__ == '__main__':
    unittest.main()
