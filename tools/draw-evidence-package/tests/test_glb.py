import json
import os
import struct
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis_suite_evidence.glb import (
    JSON_CHUNK,
    build_glb,
    validate_glb_bytes,
)


class GLBTests(unittest.TestCase):
    def test_triangle_is_valid_glb_2(self):
        data = build_glb(
            {
                "POSITION": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                "TEXCOORD_0": [(0, 0), (1, 0), (0, 1)],
            },
            [0, 1, 2],
        )
        self.assertEqual(validate_glb_bytes(data), [])
        magic, version, length = struct.unpack_from("<III", data, 0)
        self.assertEqual(magic, 0x46546C67)
        self.assertEqual(version, 2)
        self.assertEqual(length, len(data))
        json_length, kind = struct.unpack_from("<II", data, 12)
        self.assertEqual(kind, JSON_CHUNK)
        document = json.loads(data[20 : 20 + json_length].decode("utf-8"))
        self.assertEqual(document["accessors"][0]["count"], 3)
        self.assertEqual(document["meshes"][0]["primitives"][0]["mode"], 4)

    def test_invalid_index_is_rejected(self):
        with self.assertRaises(ValueError):
            build_glb({"POSITION": [(0, 0, 0)]}, [1])


if __name__ == "__main__":
    unittest.main()
