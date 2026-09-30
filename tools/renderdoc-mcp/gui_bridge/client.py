import json
import os
import socket
from pathlib import Path

from contracts import ToolError


def send(request):
    endpoint = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RenderDocMCP" / "gui-bridge.json"
    if not endpoint.exists():
        raise ToolError("gui_bridge_unavailable", "Install and enable the optional GUI extension")
    data = json.loads(endpoint.read_text())
    request = dict(request, token=data["token"])
    try:
        with socket.create_connection(("127.0.0.1", data["port"]), timeout=120) as connection:
            connection.sendall((json.dumps(request) + "\n").encode())
            with connection.makefile("rb") as reader:
                result = json.loads(reader.readline())
        if "error" in result:
            raise ToolError("gui_error", result["error"])
        return result
    except OSError as exc:
        raise ToolError("gui_bridge_unavailable", str(exc))
