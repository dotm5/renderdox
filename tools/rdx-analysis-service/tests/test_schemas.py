import json
import os
import unittest


class SchemaTests(unittest.TestCase):
    def test_required_schemas_are_versioned_json_schema(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        for name in ("capture-health.schema.json", "pass-graph.schema.json"):
            with self.subTest(name=name):
                with open(os.path.join(root, "schemas", name), "r", encoding="utf-8") as stream:
                    schema = json.load(stream)
                self.assertEqual(
                    schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
                )
                self.assertIn("schemaVersion", schema["properties"])


if __name__ == "__main__":
    unittest.main()
