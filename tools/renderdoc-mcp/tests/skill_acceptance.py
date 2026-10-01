"""Validate bilingual discovery through a compiled, relocated MCP server."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import PROTOCOL_VERSIONS, VERSION
from contracts.catalog import TOOLS
from workflows.skills import FILES, SKILL_NAMES, PREFIX, PROMPT_NAME


async def run(package, output):
    output.mkdir(parents=True, exist_ok=True)
    proof = {"version": VERSION, "protocols": [], "scope": "compiled portable skill discovery; no live game operations"}
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    environment["PATH"] = r"C:\Windows\System32;C:\Windows"
    for protocol in PROTOCOL_VERSIONS:
        with (output / (protocol + "-stderr.log")).open("wb") as log:
            process = await asyncio.create_subprocess_exec(str(package / "renderdoc-mcp.exe"),
                "--output-dir", str(output / protocol), "serve", "--stdio", cwd=r"C:\Windows",
                env=environment, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log)
            sequence = 0
            async def request(method, params):
                nonlocal sequence
                sequence += 1
                process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": sequence,
                    "method": method, "params": params}) + "\n").encode())
                await process.stdin.drain()
                while True:
                    line = await asyncio.wait_for(process.stdout.readline(), 30)
                    if not line:
                        raise RuntimeError("Server exited before replying")
                    message = json.loads(line)
                    if message.get("id") == sequence:
                        if "error" in message:
                            raise RuntimeError(message["error"])
                        return message["result"]
            async def tool(name, args):
                value = await request("tools/call", {"name": name, "arguments": args})
                assert not value.get("isError"), value
                return json.loads(value["content"][0]["text"])
            try:
                init = await request("initialize", {"protocolVersion": protocol, "capabilities": {},
                    "clientInfo": {"name": "skill-acceptance", "version": "1"}})
                assert init["serverInfo"]["version"] == VERSION
                assert init["protocolVersion"] == protocol
                assert "prompts" in init["capabilities"]
                process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
                await process.stdin.drain()
                catalog = await request("tools/list", {})
                assert {x["name"] for x in catalog["tools"]} == set(TOOLS)
                listing = await tool("list_analysis_skills", {})
                assert listing["defaultLanguage"] == "zh-CN"
                assert (await tool("get_analysis_skill", {}))["name"] == SKILL_NAMES[0]
                resources = (await request("resources/list", {}))["resources"]
                assert len(resources) == 10
                hashes = {}
                for name in SKILL_NAMES:
                    for path in FILES:
                        item = await tool("get_analysis_skill", {"name": name, "path": path})
                        resource = await request("resources/read", {"uri": PREFIX + name + "/" + path})
                        assert resource["contents"][0]["text"] == item["text"]
                        assert hashlib.sha256(item["text"].encode()).hexdigest() == item["sha256"]
                        hashes[name + "/" + path] = item["sha256"]
                prompts = await request("prompts/list", {})
                assert prompts["prompts"][0]["name"] == PROMPT_NAME
                for language, name in zip(("zh-CN", "en"), SKILL_NAMES):
                    prompt = await request("prompts/get", {"name": PROMPT_NAME,
                        "arguments": {} if language == "zh-CN" else {"language": language}})
                    assert "name: " + name + "\n" in prompt["messages"][0]["content"]["text"]
                proof["protocols"].append({"protocol": protocol, "toolCount": len(catalog["tools"]),
                    "resources": len(resources), "defaultLanguage": "zh-CN", "hashes": hashes, "status": "passed"})
            finally:
                process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), 30)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            assert process.returncode == 0, process.returncode
    proof["status"] = "passed"
    (output / "results.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "version": VERSION, "protocols": len(proof["protocols"]), "tools": len(TOOLS)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(run(Path(args.package).resolve(), Path(args.output).resolve()))
