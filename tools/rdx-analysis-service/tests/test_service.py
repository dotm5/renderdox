import io
import json
import os
import sys
import tempfile
import threading
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rdx_analysis.service import JsonRpcServer, METHODS, RDXService


def analysis(path):
    return {
        "capturePath": path,
        "captureSHA256": "A" * 64,
        "captureSizeBytes": 10,
        "status": "healthy",
        "api": "D3D12",
        "replayVersion": "1.45",
        "actionCount": 1,
        "drawCount": 1,
        "dispatchCount": 0,
        "actions": [
            {
                "eventId": 7,
                "actionId": 1,
                "name": "Draw(3)",
                "flags": ["Drawcall"],
                "children": [],
            }
        ],
        "resourceUsages": [
            {
                "resourceId": "ResourceId::2",
                "usages": [{"eventId": 7, "usage": "VS_Constants"}],
            }
        ],
        "passGraph": {"passes": [{"id": 1}]},
        "actionSignatures": [
            {
                "eventId": 7,
                "kind": "Drawcall",
                "workClass": "graphics",
                "pipelineStateHash": "P",
                "shaderHashes": ["S"],
                "inputResourceKeys": ["I"],
                "outputResourceKeys": ["O"],
                "renderTargetFormats": ["R8G8B8A8_UNORM"],
                "structuralSignature": "X",
            }
        ],
    }


class FakeRunner:
    def __call__(
        self,
        qrenderdoc,
        capture_path,
        operation,
        parameters,
        work_root,
        timeout_seconds,
        max_resource_bytes,
        cancel_event,
    ):
        if cancel_event.is_set():
            return {
                "status": "failed",
                "error": {"type": "cancelled", "message": "cancelled"},
            }
        payload = analysis(capture_path) if operation == "analyse_capture" else {
            "operation": operation,
            "parameters": parameters,
        }
        return {"status": "succeeded", "payload": payload}


class ServiceTests(unittest.TestCase):
    def make_service(self, directory):
        executable = os.path.join(directory, "dgcoreui.exe")
        capture = os.path.join(directory, "capture.rdc")
        open(executable, "wb").close()
        open(capture, "wb").close()
        return (
            RDXService(
                executable,
                os.path.join(directory, "out"),
                query_runner=FakeRunner(),
            ),
            capture,
        )

    def test_initialize_lists_all_required_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            service, _ = self.make_service(directory)
            result = service.call("initialize")
            self.assertEqual(result["protocolVersion"], 1)
            self.assertEqual(set(result["methods"]), set(METHODS))
            self.assertTrue(result["readOnlyCaptureAccess"])

    def test_session_queries_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            service, capture = self.make_service(directory)
            opened = service.call("open_capture", {"path": capture})
            session = opened["sessionId"]
            listed = service.call("list_actions", {"sessionId": session})
            self.assertEqual(listed["data"]["actions"][0]["eventId"], 7)
            action = service.call(
                "get_action", {"sessionId": session, "eventId": 7}
            )
            self.assertEqual(action["captureSHA256"], "A" * 64)
            usage = service.call(
                "get_resource_usage", {"sessionId": session, "eventId": 7}
            )
            self.assertEqual(len(usage["data"]["resources"]), 1)
            pipeline = service.call(
                "get_pipeline_state", {"sessionId": session, "eventId": 7}
            )
            self.assertEqual(pipeline["data"]["operation"], "get_pipeline_state")
            closed = service.call("close_capture", {"sessionId": session})
            self.assertTrue(closed["closed"])

    def test_json_rpc_stdio_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            service, _ = self.make_service(directory)
            source = io.StringIO(
                json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
                )
                + "\n"
            )
            destination = io.StringIO()
            JsonRpcServer(service, source, destination, workers=1).serve()
            response = json.loads(destination.getvalue())
            self.assertEqual(response["id"], 1)
            self.assertEqual(response["result"]["protocolVersion"], 1)

    def test_pre_cancelled_query_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            service, capture = self.make_service(directory)
            event = threading.Event()
            event.set()
            with self.assertRaises(Exception):
                service.call("open_capture", {"path": capture}, event)


if __name__ == "__main__":
    unittest.main()
