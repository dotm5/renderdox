import unittest

from rdx_analysis.pass_graph import build_pass_graph, owning_action_eid


class PassGraphTests(unittest.TestCase):
    def test_usage_ownership_and_dependencies_ignore_marker_names(self):
        actions = [
            {"eventId": 10, "name": "mutable marker"},
            {"eventId": 20, "name": "different marker"},
            {"eventId": 30, "name": ""},
        ]
        usages = [
            {
                "resourceId": "ResourceId::7",
                "usages": [
                    {"eventId": 9, "usage": "ColorTarget"},
                    {"eventId": 19, "usage": "PS_Resource"},
                    {"eventId": 29, "usage": "CopyDst"},
                ],
            }
        ]
        signatures = [
            {
                "eventId": 10,
                "kind": "Drawcall",
                "workClass": "graphics",
                "outputResources": ["ResourceId::7"],
                "inputResources": [],
                "outputResourceKeys": ["OUT"],
                "inputResourceKeys": [],
                "renderTargetFormats": ["RGBA8"],
                "shaderHashes": ["S1"],
                "pipelineStateHash": "P1",
                "viewport": {"width": 1},
            },
            {
                "eventId": 20,
                "kind": "Drawcall",
                "workClass": "graphics",
                "outputResources": [],
                "inputResources": ["ResourceId::7"],
                "outputResourceKeys": [],
                "inputResourceKeys": ["OUT"],
                "renderTargetFormats": [],
                "shaderHashes": ["S2"],
                "pipelineStateHash": "P2",
                "viewport": {"width": 1},
            },
        ]
        graph = build_pass_graph(actions, usages, signatures)
        self.assertEqual(owning_action_eid([10, 20, 30], 19), 20)
        self.assertEqual(
            graph["actionEdges"],
            [
                {
                    "fromEventId": 10,
                    "toEventId": 20,
                    "resourceId": "ResourceId::7",
                    "kind": "write-to-read",
                }
            ],
        )
        self.assertEqual(len(graph["passes"]), 2)
        self.assertEqual(len(graph["passes"][0]["structuralSignature"]), 64)


if __name__ == "__main__":
    unittest.main()
