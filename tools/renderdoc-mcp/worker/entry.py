"""Standalone compatible interpreter entry. Protocol uses a socket, never stdout."""
import argparse
import ctypes
import json
import os
import select
import socket
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--mode", choices=("replay", "target"), required=True)
    args = parser.parse_args()
    print("Worker starting: " + args.mode, file=sys.stderr, flush=True)
    root = os.path.abspath(args.package_root)
    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
    if os.name == "nt":
        ctypes.windll.kernel32.SetDllDirectoryW(root)
    sys.path.insert(0, os.path.join(root, "pymodules"))
    sys.path.insert(0, root)
    import renderdoc as rd
    print("RenderDoc bindings loaded", file=sys.stderr, flush=True)
    from adapters.renderdoc.replay import Replay
    from adapters.renderdoc.target import Target
    sock = socket.create_connection(("127.0.0.1", args.port))
    send = lambda value: sock.sendall((json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    print("Replay environment initialized", file=sys.stderr, flush=True)
    backend = None
    try:
        backend = Replay(rd, args.artifacts) if args.mode == "replay" else Target(rd, args.artifacts)
        send({"token": args.token, "hello": {"python": sys.version, "mode": args.mode}})
        buffer = b""
        while True:
            readable, _, _ = select.select([sock], [], [], 0 if backend.needs_pump() else 0.1)
            if readable:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                request = json.loads(line)
                print("Operation: " + request["operation"], file=sys.stderr, flush=True)
                if request["operation"] == "shutdown":
                    send({"id": request["id"], "result": {"closed": True}})
                    return
                try:
                    result = backend.call(request["operation"], request.get("arguments", {}))
                    send({"id": request["id"], "result": result})
                except Exception as exc:
                    send({"id": request["id"], "error": {"code": getattr(exc, "code", "backend_error"),
                          "message": str(exc), "traceback": traceback.format_exc()}})
            if backend.needs_pump():
                for event in backend.pump():
                    send({"event": event})
    finally:
        if backend is not None:
            backend.close()
        rd.ShutdownReplay()
        print("Replay environment shut down", file=sys.stderr, flush=True)
        sock.close()


if __name__ == "__main__":
    main()
