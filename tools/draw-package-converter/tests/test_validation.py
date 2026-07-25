import json
import os
import struct
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from draw_package_converter.converter import validate_path
from draw_package_converter.glb_validation import (
    BIN_CHUNK,
    GLB_MAGIC,
    JSON_CHUNK,
    validate_glb_bytes,
)


def minimal_glb():
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 0}],
        "bufferViews": [],
        "accessors": [],
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    binary = b""
    total = 12 + 8 + len(payload) + 8
    return (
        struct.pack("<III", GLB_MAGIC, 2, total)
        + struct.pack("<II", len(payload), JSON_CHUNK)
        + payload
        + struct.pack("<II", 0, BIN_CHUNK)
        + binary
    )


class ValidationTests(unittest.TestCase):
    def test_minimal_glb_is_valid(self):
        self.assertEqual(validate_glb_bytes(minimal_glb()), [])

    def test_truncated_glb_is_rejected(self):
        self.assertTrue(validate_glb_bytes(b"glTF"))

    def test_package_discovers_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "geometry"))
            with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as stream:
                json.dump({"kind": "draw-evidence-package"}, stream)
            with open(os.path.join(directory, "geometry", "input.glb"), "wb") as stream:
                stream.write(minimal_glb())
            result = validate_path(directory)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(len(result["files"]), 1)


if __name__ == "__main__":
    unittest.main()
