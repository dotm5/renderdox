import csv
import io
import unittest

from rdx_analysis.health import aggregate_health, health_csv, validate_health_document


class HealthTests(unittest.TestCase):
    def test_stable_order_csv_and_validation(self):
        captures = [
            {
                "capturePath": "Z,quoted.rdc",
                "captureSHA256": "A" * 64,
                "status": "degraded",
                "mainOutput": {"width": 1920, "height": 1080, "format": "RGBA8"},
            },
            {
                "capturePath": "a.rdc",
                "captureSHA256": "B" * 64,
                "status": "healthy",
            },
        ]
        document = aggregate_health(captures, {"inputs": ["test"]})
        self.assertEqual(validate_health_document(document), [])
        self.assertEqual(document["captures"][0]["capturePath"], "a.rdc")
        rows = list(csv.DictReader(io.StringIO(health_csv(document))))
        self.assertEqual(rows[1]["capturePath"], "Z,quoted.rdc")
        self.assertEqual(rows[1]["mainOutput"], "1920x1080 RGBA8")

    def test_invalid_status_is_rejected(self):
        document = aggregate_health(
            [{"capturePath": "x", "captureSHA256": None, "status": "unknown"}],
            {},
        )
        self.assertTrue(validate_health_document(document))

    def test_health_csv_is_utf8_safe_and_rfc4180_quoted(self):
        document = aggregate_health(
            [
                {
                    "capturePath": "目录/含,逗号.rdc",
                    "captureSHA256": "C" * 64,
                    "status": "failed",
                    "workerFailure": {
                        "reason": "fixture",
                        "details": "line one\nline \"two\"",
                    },
                }
            ],
            {},
        )
        text = health_csv(document)
        self.assertIn('"目录/含,逗号.rdc"', text)
        self.assertTrue(text.endswith("\r\n"))
        self.assertEqual(
            list(csv.DictReader(io.StringIO(text)))[0]["capturePath"],
            "目录/含,逗号.rdc",
        )


if __name__ == "__main__":
    unittest.main()
