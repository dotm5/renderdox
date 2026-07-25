import unittest

from rdx_analysis.replay import _format_name


class _NamedFormat:
    def Name(self):
        return "R8G8B8A8_UNORM"


class _FallbackFormat:
    type = "ResourceFormatType.Regular"


class ReplayHelperTests(unittest.TestCase):
    def test_resource_format_uses_stable_name_not_swig_pointer(self):
        self.assertEqual(_format_name(_NamedFormat()), "R8G8B8A8_UNORM")
        self.assertEqual(_format_name(_FallbackFormat()), "Regular")


if __name__ == "__main__":
    unittest.main()
