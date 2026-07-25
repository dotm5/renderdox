import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rdx_analysis.multiaction import build_multiaction_map, overlay_events_for_target


class MultiActionMapTests(unittest.TestCase):
    def test_nested_leaf_draws_and_target_filtering(self):
        actions = [
            {
                "eventId": 10,
                "actionId": 1,
                "name": "ExecuteIndirect",
                "flags": ["MultiAction", "Indirect"],
                "children": [11, 12, 14],
            },
            {
                "eventId": 11,
                "actionId": 2,
                "name": "Draw 0",
                "flags": ["Drawcall"],
                "children": [],
                "drawIndex": 0,
                "outputResources": ["resource-color"],
                "depthOutput": None,
            },
            {
                "eventId": 12,
                "actionId": 3,
                "name": "Dispatch",
                "flags": ["Dispatch"],
                "children": [],
            },
            {
                "eventId": 14,
                "actionId": 4,
                "name": "Nested",
                "flags": ["MultiAction"],
                "children": [15],
            },
            {
                "eventId": 15,
                "actionId": 5,
                "name": "Draw 1",
                "flags": ["Drawcall", "Indexed", "Instanced"],
                "children": [],
                "drawIndex": 1,
                "numIndices": 6,
                "numInstances": 2,
                "outputResources": [],
                "depthOutput": "resource-depth",
            },
        ]

        result = build_multiaction_map(actions)
        self.assertEqual(result["parentCount"], 2)
        root = result["parents"][0]
        self.assertEqual(root["effectiveEventId"], 15)
        self.assertEqual(root["overlayChildEventIds"], [11, 15])
        self.assertEqual(overlay_events_for_target(root, "resource-color"), [11])
        self.assertEqual(overlay_events_for_target(root, "resource-depth"), [15])
        self.assertEqual(overlay_events_for_target(root, None), [11, 15])

    def test_non_multi_parent_is_not_mapped(self):
        result = build_multiaction_map(
            [
                {
                    "eventId": 1,
                    "actionId": 1,
                    "flags": ["PushMarker"],
                    "children": [2],
                },
                {
                    "eventId": 2,
                    "actionId": 2,
                    "flags": ["Drawcall"],
                    "children": [],
                },
            ]
        )
        self.assertEqual(result, {"parentCount": 0, "childDrawCount": 0, "parents": []})


if __name__ == "__main__":
    unittest.main()
