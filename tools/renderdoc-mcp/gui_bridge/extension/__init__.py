import json
import os
import queue
import secrets
import socket
import threading
from pathlib import Path

import renderdoc as rd
from PySide2.QtCore import QTimer

_bridge = None


class Bridge:
    def __init__(self, ctx):
        self.ctx, self.pending, self.closed = ctx, queue.Queue(), threading.Event()
        self.active, self.processing = None, False
        self.token = secrets.token_hex(32)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.25)
        self.endpoint = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RenderDocMCP" / "gui-bridge.json"
        self.endpoint.parent.mkdir(parents=True, exist_ok=True)
        self.endpoint.write_text(json.dumps({"port": self.listener.getsockname()[1], "token": self.token, "pid": os.getpid()}))
        self.timer = QTimer()
        self.timer.timeout.connect(self.process)
        self.timer.start(100)
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while not self.closed.is_set():
            connection = None
            try:
                connection, _ = self.listener.accept()
                connection.settimeout(5)
                with connection.makefile("rb") as reader:
                    request = json.loads(reader.readline())
                if request.pop("token", None) != self.token:
                    connection.close()
                    continue
                self.pending.put((connection, request))
            except socket.timeout:
                if connection:
                    connection.close()
            except (ValueError, OSError):
                if connection:
                    connection.close()

    def process(self):
        # QTimer is owned by the UI thread; native replay itself remains under
        # the GUI's replay manager. No target connection is borrowed here.
        if self.processing:
            return
        if self.active is None:
            if self.pending.empty():
                return
            self.active = self.pending.get()
        connection, request = self.active
        self.processing = True
        try:
            if request["operation"] == "gui_select_event":
                path = os.path.abspath(request["path"])
                if not request.get("loadRequested") and (not self.ctx.IsCaptureLoaded() or os.path.normcase(self.ctx.GetCaptureFilename()) != os.path.normcase(path)):
                    request["loadRequested"] = True
                    self.ctx.LoadCapture(path, rd.ReplayOptions(), path, False, True)
                if self.ctx.IsCaptureLoading():
                    return  # QTimer retries without blocking the UI thread.
                if not self.ctx.IsCaptureLoaded() or os.path.normcase(self.ctx.GetCaptureFilename()) != os.path.normcase(path):
                    raise RuntimeError("GUI did not load the requested capture")
                self.ctx.SetEventID([], request["eventId"], request["eventId"], True)
            result = {"connected": True, "pid": os.getpid(), "captureLoaded": self.ctx.IsCaptureLoaded(),
                      "path": self.ctx.GetCaptureFilename() if self.ctx.IsCaptureLoaded() else None}
        except Exception as exc:
            result = {"error": str(exc)}
        finally:
            self.processing = False
        try:
            connection.sendall((json.dumps(result) + "\n").encode())
        except OSError:
            pass
        connection.close()
        self.active = None

    def close(self):
        self.closed.set()
        self.timer.stop()
        self.listener.close()
        while not self.pending.empty():
            self.pending.get()[0].close()
        if self.active:
            self.active[0].close()
            self.active = None
        if self.endpoint.exists():
            data = json.loads(self.endpoint.read_text())
            if data.get("token") == self.token:
                self.endpoint.unlink()


def register(version, ctx):
    global _bridge
    _bridge = Bridge(ctx)


def unregister():
    global _bridge
    if _bridge:
        _bridge.close()
        _bridge = None
