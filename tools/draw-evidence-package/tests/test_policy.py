import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis_suite_evidence.policy import texture_export_policy


class TexturePolicyTests(unittest.TestCase):
    def test_lossless_routes(self):
        self.assertEqual(texture_export_policy("BC7_UNORM", "UNorm")["container"], "DDS")
        self.assertEqual(texture_export_policy("R16G16B16A16_FLOAT", "Float")["container"], "EXR")
        self.assertEqual(texture_export_policy("R8G8B8A8_SRGB", "UNorm")["container"], "PNG")
        self.assertEqual(texture_export_policy("ASTC_4x4", "UNorm")["container"], "RAW")
        self.assertEqual(
            texture_export_policy("D32_FLOAT", "Float", is_depth=True)["container"], "EXR"
        )


if __name__ == "__main__":
    unittest.main()
