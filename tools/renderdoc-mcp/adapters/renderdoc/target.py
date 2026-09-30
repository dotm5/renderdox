import os
import time

from contracts import ToolError
from .convert import artifact, enum, plain


class Target:
    def __init__(self, rd, directory):
        self.rd, self.directory, self.connection = rd, directory, None
        self.captures = {}
        self.last_progress = -1

    def needs_pump(self):
        return self.connection is not None and self.connection.Connected()

    def close(self):
        if self.connection:
            self.connection.Shutdown()
            self.connection = None

    def function(self, name):
        # Product identity changes the exported C names in this fork. SWIG may
        # retain the upstream Python name depending on the binding generation.
        function = getattr(self.rd, name, None) or getattr(self.rd, "DCOMP_" + name, None)
        if function is None:
            raise ToolError("unsupported", "Public API unavailable: " + name)
        return function

    def info(self):
        conn = self.connection
        return {"connected": bool(conn and conn.Connected()), "target": conn.GetTarget() if conn else None,
                "api": conn.GetAPI() if conn else None, "pid": conn.GetPID() if conn else None,
                "busyClient": conn.GetBusyClient() if conn else None}

    def call(self, name, args):
        if name == "list_targets":
            values, ident = [], 0
            while True:
                ident = self.function("EnumerateRemoteTargets")(args.get("host", ""), ident)
                if not ident:
                    break
                # Discovery must not open a control connection: that would
                # consume the only slot and race the user's GUI.
                values.append({"host": args.get("host", ""), "ident": int(ident)})
            return {"targets": values}
        if name == "connect_target":
            self.close()
            self.connection = self.function("CreateTargetControl")(args.get("host", ""), args["ident"],
                    args.get("clientName", "RenderDoc MCP"), args.get("takeover", False))
            if not self.connection:
                raise ToolError("connection_failed", "Target did not accept connection")
            result = self.info()
            if result["busyClient"]:
                self.close()
                raise ToolError("target_busy", "Target controlled by " + result["busyClient"])
            if not result["connected"]:
                self.close()
                raise ToolError("connection_failed", "Target disconnected during handshake")
            return result
        if name in ("launch_and_capture", "inject_process"):
            options = self.rd.CaptureOptions()
            for key, value in args.get("captureOptions", {}).items():
                if not hasattr(options, key):
                    raise ToolError("invalid_option", key)
                setattr(options, key, value)
            environment = []
            for item in args.get("environment", []):
                mod = self.rd.EnvironmentModification()
                mod.name, mod.value = item["name"], item["value"]
                mod.mod = getattr(self.rd.EnvMod, item.get("mod", "Set"))
                mod.sep = getattr(self.rd.EnvSep, item.get("sep", "NoSep"))
                environment.append(mod)
            if name == "launch_and_capture":
                result = self.function("ExecuteAndInject")(args["application"], args.get("workingDirectory", ""),
                    args.get("commandLine", ""), environment, args.get("captureFile", ""), options, False)
            else:
                result = self.function("InjectIntoProcess")(args["pid"], environment, args.get("captureFile", ""), options, False)
            info = plain(result)
            if not result.ident:
                raise ToolError("injection_failed", str(result.result))
            return info
        if name == "get_connection":
            return self.info()
        if not self.needs_pump():
            raise ToolError("disconnected", "Target connection is not active")
        if name == "cycle_capture_window":
            self.connection.CycleActiveWindow()
        elif name in ("capture_now", "capture_at_frame"):
            if name == "capture_now":
                self.connection.TriggerCapture(args.get("framesPerCapture", 1))
            else:
                self.connection.QueueCapture(args["frameNumber"], args.get("framesPerCapture", 1))
            return {"requested": True, "requestedMonotonic": time.monotonic(),
                    "requestedUnix": time.time(), "correlation": "API does not return a per-request token"}
        elif name == "save_capture":
            identifier = args["remoteCaptureId"]
            if identifier not in self.captures:
                raise ToolError("missing_capture", str(identifier))
            path = os.path.abspath(args["path"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.connection.CopyCapture(identifier, path)
            return {"copyRequested": True, "remoteCaptureId": identifier, "path": path}
        else:
            raise ToolError("unsupported", name)
        return self.info()

    def pump(self):
        message = self.connection.ReceiveMessage(None)
        kind = enum(message.type, self.rd.TargetControlMessageType)
        if kind in ("Noop", "Unknown"):
            return []
        payload = {"type": kind, "receivedUnix": time.time()}
        if kind in ("NewCapture", "CaptureCopied"):
            data = message.newCapture
            payload["capture"] = {"remoteCaptureId": int(data.captureId), "frameNumber": int(data.frameNumber),
                "timestamp": int(data.timestamp), "byteSize": int(data.byteSize), "path": str(data.path),
                "local": bool(data.local), "title": str(data.title), "api": str(data.api),
                "thumbWidth": int(data.thumbWidth), "thumbHeight": int(data.thumbHeight)}
            if kind == "NewCapture":
                self.captures[int(data.captureId)] = payload["capture"]
                if data.thumbnail:
                    payload["capture"]["thumbnailRGB"] = artifact(self.directory, bytes(data.thumbnail), "rgb")
        elif kind == "CaptureProgress":
            payload["progress"] = float(message.capProgress)
        elif kind == "RegisterAPI":
            payload["api"] = plain(message.apiUse)
        elif kind == "NewChild":
            payload["child"] = plain(message.newChild)
        elif kind == "Busy":
            payload["busy"] = plain(message.busy)
        elif kind == "CapturableWindowCount":
            payload["windowCount"] = int(message.capturableWindowCount)
        if not self.connection.Connected():
            payload["connected"] = False
        return [payload]
