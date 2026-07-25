import json
import os
import tempfile
import unittest

from rdx_analysis.cli import expand_inputs


class InputTests(unittest.TestCase):
    def test_directory_manifest_pairing_and_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            first = os.path.join(directory, "A.rdc")
            nested = os.path.join(directory, "nested")
            os.makedirs(nested)
            second = os.path.join(nested, "b.rdc")
            open(first, "wb").close()
            open(second, "wb").close()
            manifest = os.path.join(directory, "captures.json")
            with open(manifest, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "captures": [
                            {"path": "A.rdc", "pairId": "pair-1", "platform": "pc"},
                            {"path": os.path.join("nested", "b.rdc")},
                        ]
                    },
                    stream,
                )

            non_recursive = expand_inputs([directory], recursive=False)
            self.assertEqual([os.path.basename(item[0]) for item in non_recursive], ["A.rdc"])
            recursive = expand_inputs([directory, manifest], recursive=True)
            self.assertEqual(len(recursive), 2)
            self.assertEqual(recursive[0][0], os.path.abspath(first))


if __name__ == "__main__":
    unittest.main()
