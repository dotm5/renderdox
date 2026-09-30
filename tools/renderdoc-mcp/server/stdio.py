import asyncio
import base64
import copy
import json
import os
import sys
from pathlib import Path

from contracts import PROTOCOL_VERSIONS, ToolError, VERSION
from contracts.catalog import TOOLS


class StdioServer:
    def __init__(self, service):
        self.service = service
        self.output = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
        # All ordinary Python output is a log. The retained handle is solely
        # owned by the protocol writer task.
        sys.stdout = sys.stderr
        self.queue, self.requests = asyncio.Queue(), {}
        self.initialized = False
        self.negotiated = False
        self.protocol = None

    async def write_loop(self):
        while True:
            message = await self.queue.get()
            if message is None:
                break
            data = (json.dumps(message, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
            await asyncio.to_thread(self.output.write, data)

    async def emit(self, message):
        await self.queue.put(message)

    def tool_result(self, name, value, args):
        contents = [{"type": "text", "text": json.dumps(value, ensure_ascii=False, allow_nan=False)}]
        seen = set()
        def collect(item):
            if isinstance(item, dict):
                if "artifactId" in item and "path" in item and item["artifactId"] not in seen:
                    seen.add(item["artifactId"])
                    path = Path(item["path"])
                    if item.get("mimeType") == "image/png" and path.is_file() and args.get("inline", True):
                        contents.append({"type": "image", "data": base64.b64encode(path.read_bytes()).decode(), "mimeType": "image/png"})
                    else:
                        uri = "renderdoc://artifact/" + item["artifactId"]
                        if self.protocol == "2024-11-05":
                            contents.append({"type": "resource", "resource": {"uri": uri,
                                "mimeType": "text/plain", "text": "Local artifact: " + str(path)}})
                        else:
                            contents.append({"type": "resource_link", "uri": uri,
                                             "name": path.name, "mimeType": item.get("mimeType", "application/octet-stream"),
                                             "description": "Local artifact: " + str(path)})
                for v in item.values():
                    collect(v)
            elif isinstance(item, list):
                for v in item:
                    collect(v)
        collect(value)
        result = {"content": contents, "isError": False}
        if self.protocol != "2024-11-05":
            result["structuredContent"] = value
        return result

    async def dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            self.protocol = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            self.negotiated = True
            return {"protocolVersion": self.protocol, "capabilities": {"tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False}},
                    "serverInfo": {"name": "renderdoc-portable", "version": VERSION},
                    "instructions": "Open/capture/align operations return jobId. Poll get_job until completion. EIDs and ResourceIds are capture-local. Use get_draw_evidence for atomic investigation; Diff is observational."}
        if method == "ping":
            return {}
        if not self.initialized:
            raise ToolError("not_initialized", "Send initialize then notifications/initialized")
        if method == "tools/list":
            return {"tools": list(TOOLS.values())}
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            try:
                value = await self.service.call(name, args)
                # Job/connection dictionaries belong to the event loop. Copy
                # before moving JSON/image presentation to an OS thread.
                return await asyncio.to_thread(self.tool_result, name, copy.deepcopy(value), args)
            except Exception as exc:
                error = exc.payload() if isinstance(exc, ToolError) else {"code": type(exc).__name__, "message": str(exc)}
                return {"content": [{"type": "text", "text": json.dumps({"error": error}, ensure_ascii=False)}], "isError": True}
        if method == "resources/list":
            return {"resources": [{"uri": "renderdoc://artifact/" + key, "name": Path(value["path"]).name,
                                  "mimeType": value.get("mimeType", "application/octet-stream")}
                                 for key, value in self.service.db["artifacts"].items()]}
        if method == "resources/read":
            prefix = "renderdoc://artifact/"
            uri = params.get("uri", "")
            if not uri.startswith(prefix):
                raise ToolError("missing_artifact", uri)
            value = self.service.get(self.service.db["artifacts"], uri[len(prefix):], "artifact")
            data = Path(value["path"]).read_bytes()
            mime = value.get("mimeType", "application/octet-stream")
            content = {"uri": uri, "mimeType": mime}
            if mime.startswith("text/") or mime == "application/json":
                content["text"] = data.decode("utf-8")
            else:
                content["blob"] = base64.b64encode(data).decode()
            return {"contents": [content]}
        raise ToolError("method_not_found", method)

    async def handle(self, message):
        request_id = message["id"]
        token = message.get("params", {}).get("_meta", {}).get("progressToken")
        async def progress():
            elapsed = 0
            while True:
                await asyncio.sleep(2)
                elapsed += 2
                await self.emit({"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                    "progressToken": token, "progress": elapsed, "message": "Native operation running (%ds)" % elapsed}})
        ticker = asyncio.create_task(progress()) if token is not None else None
        try:
            result = await self.dispatch(message.get("method", ""), message.get("params", {}))
            await self.emit({"jsonrpc": "2.0", "id": request_id, "result": result})
        except asyncio.CancelledError:
            # Cancellation ends the client wait, while the supervisor retains
            # ownership of any native operation still executing.
            pass
        except Exception as exc:
            code = -32601 if getattr(exc, "code", "") == "method_not_found" else -32602
            await self.emit({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": str(exc)}})
        finally:
            if ticker:
                ticker.cancel()
                await asyncio.gather(ticker, return_exceptions=True)
            self.requests.pop(request_id, None)

    async def run(self):
        writer = asyncio.create_task(self.write_loop())
        try:
            while True:
                line = await asyncio.to_thread(sys.stdin.buffer.readline)
                if not line:
                    break
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                        await self.emit({"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                                         "error": {"code": -32600, "message": "Invalid JSON-RPC request"}})
                        continue
                    if "id" not in message:
                        if message["method"] == "notifications/initialized" and self.negotiated:
                            self.initialized = True
                        elif message["method"] == "notifications/cancelled":
                            task = self.requests.get(message.get("params", {}).get("requestId"))
                            if task:
                                task.cancel()
                        continue
                    # Initialization is completed before accepting subsequent
                    # notifications, even when a client pipelines input lines.
                    if message["method"] == "initialize":
                        await self.handle(message)
                    else:
                        self.requests[message["id"]] = asyncio.create_task(self.handle(message))
                except (ValueError, TypeError):
                    await self.emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            await asyncio.gather(*list(self.requests.values()), return_exceptions=True)
            await self.service.close()
        finally:
            await self.emit(None)
            await writer
            self.output.close()
