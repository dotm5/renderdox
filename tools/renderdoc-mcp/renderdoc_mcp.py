import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from contracts import VERSION


def locations(args):
    if getattr(sys, "frozen", False):
        default_package = Path(sys.executable).resolve().parent
        default_source = default_package / "mcp" / "source"
    else:
        default_source = Path(__file__).resolve().parent
        default_package = default_source.parents[1] / "x64" / "Release"
    package = Path(args.package_root or default_package).resolve()
    source = Path(args.source_root or default_source).resolve()
    interpreter = Path(args.worker_python or package / "mcp" / "worker-runtime" / "python.exe").resolve()
    output = Path(args.output_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RenderDocMCP" / "data").resolve()
    return package, source, interpreter, output


def main():
    parser = argparse.ArgumentParser(description="Portable RenderDoc MCP")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--package-root")
    parser.add_argument("--source-root")
    parser.add_argument("--worker-python")
    parser.add_argument("--output-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--stdio", action="store_true", default=True)
    config = sub.add_parser("config", help="Print client config without modifying client settings")
    config.add_argument("--format", choices=("json", "codex"), default="json")
    invoke = sub.add_parser("call", help="Direct tool invocation for local investigation")
    invoke.add_argument("tool")
    invoke.add_argument("--arguments", default="{}")
    sub.add_parser("install-gui-bridge", help="Install the optional extension; enable it in the GUI extension manager")
    args = parser.parse_args()
    package, source, interpreter, output = locations(args)
    if args.command == "config":
        command = str(Path(sys.executable).resolve())
        launch_args = [] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve())]
        launch_args += ["--package-root", str(package), "--source-root", str(source), "--worker-python", str(interpreter),
                        "--output-dir", str(output), "serve", "--stdio"]
        if args.format == "codex":
            print('[mcp_servers.renderdoc]\ncommand = ' + json.dumps(command) + '\nargs = ' + json.dumps(launch_args))
        else:
            print(json.dumps({"mcpServers": {"renderdoc": {"command": command, "args": launch_args}}}, indent=2))
        return
    if args.command == "install-gui-bridge":
        # RenderDoc extension discovery is relative to the product's config
        # directory. Use the current product identity shipped alongside the UI.
        identity_path = package / "mcp" / "component-manifest.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8-sig")) if identity_path.exists() else {}
        destination = Path(os.environ["APPDATA"]) / identity.get("configNamespace", "DComp") / "extensions" / "renderdoc_mcp_bridge"
        shutil.copytree(source / "gui_bridge" / "extension", destination, dirs_exist_ok=True)
        print(json.dumps({"extension": str(destination), "next": "Enable RenderDoc MCP Bridge in the GUI extension manager"}))
        return
    from supervisor.service import Service
    from server.stdio import StdioServer
    async def run():
        service = Service(package, source, interpreter, output)
        if args.command == "serve":
            await StdioServer(service).run()
        else:
            try:
                result = await service.call(args.tool, json.loads(args.arguments))
                if "jobId" in result:
                    await service.tasks[result["jobId"]]
                    result = service.db["jobs"][result["jobId"]]
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                await service.close()
    asyncio.run(run())


if __name__ == "__main__":
    main()
