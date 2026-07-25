import json
import os
import tempfile
import unittest

from rdx_analysis.common import atomic_write_json, sha256_file, structural_hash


class CommonTests(unittest.TestCase):
    def test_atomic_json_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "unicode-结果.json")
            atomic_write_json(path, {"schemaVersion": 1, "text": "行,\"\n"})
            with open(path, "r", encoding="utf-8") as stream:
                self.assertEqual(json.load(stream)["text"], "行,\"\n")
            self.assertEqual(len(sha256_file(path)), 64)
            self.assertEqual(
                structural_hash({"b": 2, "a": 1}),
                structural_hash({"a": 1, "b": 2}),
            )


if __name__ == "__main__":
    unittest.main()
