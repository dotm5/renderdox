"""Owned UE capture/replay and per-target inventory; does not deploy DLLs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from run import inventory


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--exe", required=True)
    p.add_argument("--bin", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ab", default="", choices=["", "loader-iat", "system-dxgi"])
    a = p.parse_args()
    root, binary = Path(a.output).resolve(), Path(a.bin).resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["DCOMP_DX_CLOSURE"] = "1"
    env["CLOSURE_SEMANTICS"] = "1"
    env["DCOMP_DX_CLOSURE_LOG"] = str(root / "coverage")
    env["DCOMP_DX_CLOSURE_AB"] = a.ab
    worker = Path(__file__).with_name("replay_worker.py").resolve()

    def execute(job, name):
        path = root / (name + "-job.json")
        path.write_text(json.dumps(job))
        env["CLOSURE_JOB"] = str(path)
        result = subprocess.run([str(binary / "dgcoreui.exe"), "--python", str(worker)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        (root / (name + ".log")).write_bytes(result.stdout)
        return json.loads(Path(job["output"]).read_text())

    launch = execute({"unreal": True, "exe": str(Path(a.exe).resolve()),
                      "capturePrefix": str(root / "ue"), "frame": 300,
                      "args": "-dx12 -windowed -ResX=640 -ResY=360 -nosound -unattended -novsync -benchmark -fps=60 -deterministic",
                      "output": str(root / "launch.json")}, "launch")
    env["DCOMP_DX_CLOSURE"] = "0"
    env["DCOMP_DX_CLOSURE_AB"] = ""
    replay = execute({"captures": launch["captures"], "output": str(root / "replay.json")}, "replay")
    targetlog = root / ("coverage.%s.log" % launch["pid"])
    result = {"abMode": a.ab,
              "coreSHA256": hashlib.sha256((binary / "dgcore.dll").read_bytes()).hexdigest(),
              "launch": launch, "replay": replay,
              "inventory": inventory(targetlog) if targetlog.exists() else None}
    (root / "results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"abMode": a.ab, "captures": len(launch["captures"]),
                      "replayStatuses": [v.get("status") for v in replay.values()],
                      "inlinePeak": result["inventory"]["inlinePeak"] if result["inventory"] else None,
                      "iatWrites": result["inventory"]["iatDistinctWrites"] if result["inventory"] else None}))


if __name__ == "__main__":
    main()
