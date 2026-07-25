import json
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import SCHEMA_VERSION, TOOL_VERSION
from .query_launcher import run_query


PROTOCOL_VERSION = 1
METHODS = (
    "open_capture",
    "close_capture",
    "get_capture_summary",
    "list_actions",
    "get_action",
    "get_pipeline_state",
    "get_resource_usage",
    "get_shader",
    "get_shader_reflection",
    "get_buffer_data",
    "save_texture",
    "get_post_vs_data",
    "build_pass_graph",
    "export_action_evidence",
    "compare_action_signatures",
)


class ProtocolError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data


def _summary(analysis):
    fields = (
        "capturePath",
        "captureSHA256",
        "captureSizeBytes",
        "status",
        "api",
        "driver",
        "gpuVendor",
        "actionCount",
        "drawCount",
        "dispatchCount",
        "executeIndirectCount",
        "multiActionCount",
        "indirectActionCount",
        "shaderCount",
        "textureCount",
        "bufferCount",
        "mainOutput",
        "deviceLost",
        "unsupportedFeature",
        "warningCount",
        "errorCount",
        "replayVersion",
        "analysisDurationMs",
        "peakMemoryBytes",
    )
    return {field: analysis.get(field) for field in fields if field in analysis}


class RDXService:
    def __init__(
        self,
        qrenderdoc,
        output_root,
        timeout_seconds=300,
        max_resource_bytes=16 * 1024 * 1024,
        max_sessions=8,
        query_runner=run_query,
    ):
        self.qrenderdoc = os.path.abspath(qrenderdoc)
        self.output_root = os.path.abspath(output_root)
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_resource_bytes = max(1, int(max_resource_bytes))
        self.max_sessions = max(1, int(max_sessions))
        self.query_runner = query_runner
        self.sessions = {}
        self.lock = threading.RLock()
        os.makedirs(self.output_root, exist_ok=True)

    def _session(self, parameters):
        session_id = str(parameters.get("sessionId", ""))
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ProtocolError(-32001, "Unknown or closed sessionId")
        return session_id, session

    def _envelope(self, session, data, event_id=None):
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "toolVersion": TOOL_VERSION,
            "captureSHA256": session["analysis"]["captureSHA256"],
            "eventId": int(event_id) if event_id is not None else None,
            "sourceVersion": session["analysis"].get("replayVersion"),
            "data": data,
        }

    def _query(self, session_id, session, operation, parameters, cancel_event):
        work_root = os.path.join(self.output_root, "s", session_id)
        result = self.query_runner(
            self.qrenderdoc,
            session["capturePath"],
            operation,
            parameters,
            work_root,
            self.timeout_seconds,
            self.max_resource_bytes,
            cancel_event,
        )
        if result.get("status") != "succeeded":
            error = result.get("error", {})
            error_type = error.get("type", "query-failed")
            code = -32800 if error_type == "cancelled" else -32002
            raise ProtocolError(code, error.get("message", error_type), result)
        return result["payload"]

    def call(self, method, parameters=None, cancel_event=None):
        parameters = parameters or {}
        cancel_event = cancel_event or threading.Event()
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "schemaVersion": SCHEMA_VERSION,
                "toolVersion": TOOL_VERSION,
                "transport": "json-rpc-2.0-stdio",
                "readOnlyCaptureAccess": True,
                "methods": list(METHODS),
                "limits": {
                    "maxRequestBytes": 1024 * 1024,
                    "maxResourceBytes": self.max_resource_bytes,
                    "timeoutSeconds": self.timeout_seconds,
                    "maxSessions": self.max_sessions,
                },
            }
        if method not in METHODS:
            raise ProtocolError(-32601, "Method not found: " + method)

        if method == "open_capture":
            capture_path = os.path.abspath(str(parameters.get("path", "")))
            if not os.path.isfile(capture_path):
                raise ProtocolError(-32602, "Capture path does not exist")
            with self.lock:
                if len(self.sessions) >= self.max_sessions:
                    raise ProtocolError(-32003, "Session limit reached")
            transient_id = uuid.uuid4().hex[:12]
            work_root = os.path.join(self.output_root, "s", transient_id)
            result = self.query_runner(
                self.qrenderdoc,
                capture_path,
                "analyse_capture",
                {},
                work_root,
                self.timeout_seconds,
                self.max_resource_bytes,
                cancel_event,
            )
            if result.get("status") != "succeeded":
                error = result.get("error", {})
                code = -32800 if error.get("type") == "cancelled" else -32002
                raise ProtocolError(code, error.get("message", "Capture analysis failed"), result)
            analysis = result["payload"]
            if analysis.get("status") == "failed":
                raise ProtocolError(-32002, "Capture could not be replayed", analysis)
            session = {
                "capturePath": capture_path,
                "analysis": analysis,
                "workRoot": os.path.dirname(work_root),
            }
            with self.lock:
                self.sessions[transient_id] = session
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "sessionId": transient_id,
                "captureSHA256": analysis["captureSHA256"],
                "sourceVersion": analysis.get("replayVersion"),
                "summary": _summary(analysis),
            }

        session_id, session = self._session(parameters)
        analysis = session["analysis"]
        if method == "close_capture":
            with self.lock:
                self.sessions.pop(session_id, None)
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "sessionId": session_id,
                "closed": True,
                "artifactsRetained": True,
            }
        if method == "get_capture_summary":
            return self._envelope(session, _summary(analysis))
        if method == "list_actions":
            offset = max(0, int(parameters.get("offset", 0)))
            limit = min(10000, max(1, int(parameters.get("limit", 1000))))
            actions = analysis.get("actions", [])
            name_contains = str(parameters.get("nameContains", "")).casefold()
            flag = parameters.get("flag")
            if name_contains:
                actions = [
                    item
                    for item in actions
                    if name_contains in item.get("name", "").casefold()
                ]
            if flag:
                actions = [item for item in actions if flag in item.get("flags", [])]
            return self._envelope(
                session,
                {
                    "total": len(actions),
                    "offset": offset,
                    "limit": limit,
                    "actions": actions[offset : offset + limit],
                },
            )
        if method == "get_action":
            event_id = int(parameters.get("eventId", 0))
            action = next(
                (
                    item
                    for item in analysis.get("actions", [])
                    if int(item["eventId"]) == event_id
                ),
                None,
            )
            if action is None:
                raise ProtocolError(-32602, "No action exists at the requested EID")
            return self._envelope(session, action, event_id)
        if method == "get_resource_usage":
            resource_identifier = parameters.get("resourceId")
            event_id = parameters.get("eventId")
            records = analysis.get("resourceUsages", [])
            if resource_identifier:
                records = [
                    item
                    for item in records
                    if item.get("resourceId") == resource_identifier
                ]
            if event_id is not None:
                selected = []
                for item in records:
                    usages = [
                        usage
                        for usage in item.get("usages", [])
                        if int(usage["eventId"]) == int(event_id)
                    ]
                    if usages:
                        selected.append(
                            {"resourceId": item["resourceId"], "usages": usages}
                        )
                records = selected
            total = len(records)
            offset = max(0, int(parameters.get("offset", 0)))
            limit = min(10000, max(1, int(parameters.get("limit", 1000))))
            return self._envelope(
                session,
                {
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "resources": records[offset : offset + limit],
                },
                int(event_id) if event_id is not None else None,
            )
        if method == "build_pass_graph":
            return self._envelope(session, analysis.get("passGraph", {}))
        if method == "compare_action_signatures":
            other_id = str(parameters.get("otherSessionId", session_id))
            with self.lock:
                other = self.sessions.get(other_id)
            if other is None:
                raise ProtocolError(-32602, "otherSessionId is unknown or closed")
            left_event = parameters.get("eventId")
            right_event = parameters.get("otherEventId", left_event)
            left = analysis.get("actionSignatures", [])
            right = other["analysis"].get("actionSignatures", [])
            if left_event is not None:
                left = [item for item in left if int(item["eventId"]) == int(left_event)]
            if right_event is not None:
                right = [item for item in right if int(item["eventId"]) == int(right_event)]
            total = min(len(left), len(right))
            offset = max(0, int(parameters.get("offset", 0)))
            limit = min(10000, max(1, int(parameters.get("limit", 1000))))
            pairs = []
            for index in range(offset, min(total, offset + limit)):
                first, second = left[index], right[index]
                fields = (
                    "kind",
                    "workClass",
                    "pipelineStateHash",
                    "shaderHashes",
                    "inputResourceKeys",
                    "outputResourceKeys",
                    "renderTargetFormats",
                    "structuralSignature",
                )
                differences = [
                    field for field in fields if first.get(field) != second.get(field)
                ]
                pairs.append(
                    {
                        "leftEventId": first["eventId"],
                        "rightEventId": second["eventId"],
                        "equal": not differences,
                        "differentFields": differences,
                        "leftSignature": first.get("structuralSignature"),
                        "rightSignature": second.get("structuralSignature"),
                    }
                )
            return self._envelope(
                session,
                {
                    "otherCaptureSHA256": other["analysis"]["captureSHA256"],
                    "leftCount": len(left),
                    "rightCount": len(right),
                    "offset": offset,
                    "limit": limit,
                    "pairCount": total,
                    "pairs": pairs,
                },
                int(left_event) if left_event is not None else None,
            )

        event_id = parameters.get("eventId")
        payload = self._query(
            session_id, session, method, parameters, cancel_event
        )
        return self._envelope(
            session, payload, int(event_id) if event_id is not None else None
        )


class JsonRpcServer:
    def __init__(self, service, input_stream=None, output_stream=None, workers=2):
        self.service = service
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self.executor = ThreadPoolExecutor(max_workers=max(1, int(workers)))
        self.output_lock = threading.Lock()
        self.requests_lock = threading.Lock()
        self.cancellations = {}

    def _write(self, document):
        encoded = json.dumps(
            document, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        with self.output_lock:
            self.output.write(encoded + "\n")
            self.output.flush()

    def _respond(self, request, cancel_event):
        request_id = request.get("id")
        try:
            result = self.service.call(
                request.get("method"), request.get("params"), cancel_event
            )
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except ProtocolError as exception:
            error = {"code": exception.code, "message": exception.message}
            if exception.data is not None:
                error["data"] = exception.data
            response = {"jsonrpc": "2.0", "id": request_id, "error": error}
        except BaseException as exception:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exception)},
            }
        if request_id is not None:
            self._write(response)
        with self.requests_lock:
            self.cancellations.pop(str(request_id), None)

    def serve(self):
        try:
            for line in self.input:
                if len(line.encode("utf-8")) > 1024 * 1024:
                    self._write(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": "Request exceeds 1 MiB"},
                        }
                    )
                    continue
                try:
                    request = json.loads(line)
                    if (
                        not isinstance(request, dict)
                        or request.get("jsonrpc") != "2.0"
                        or not isinstance(request.get("method"), str)
                    ):
                        raise ValueError("Invalid JSON-RPC request")
                except ValueError as exception:
                    self._write(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32700, "message": str(exception)},
                        }
                    )
                    continue
                if request["method"] == "$/cancelRequest":
                    target = str((request.get("params") or {}).get("id"))
                    with self.requests_lock:
                        event = self.cancellations.get(target)
                    if event is not None:
                        event.set()
                    continue
                request_id = request.get("id")
                cancel_event = threading.Event()
                if request_id is not None:
                    with self.requests_lock:
                        self.cancellations[str(request_id)] = cancel_event
                self.executor.submit(self._respond, request, cancel_event)
        finally:
            with self.requests_lock:
                for event in self.cancellations.values():
                    event.set()
            self.executor.shutdown(wait=True)
