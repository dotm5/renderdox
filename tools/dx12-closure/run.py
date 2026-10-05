"""Capture sample matrix and compare diagnostic-off/on semantic replay fingerprints."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def inventory(path):
    kinds = collections.Counter()
    inline, inline_sites, iat, dynamic, exports = set(), {}, set(), set(), set()
    peak = 0
    anomalies = []
    for line in path.read_text(errors="replace").splitlines():
        m = re.search(r"kind=(\S+) site=(.*?) object=(\S+) related=(\S+)", line)
        if not m:
            continue
        kind, site, obj, related = m.groups()
        kinds[kind] += 1
        if kind in ("inline_install", "inline_chain"):
            inline.add(obj)
            inline_sites[obj] = site
            peak = max(peak, len(inline))
        elif kind == "inline_remove":
            inline.discard(obj)
        elif kind == "iat_write":
            iat.add((related, obj, site))
        elif kind == "dynamic_redirect":
            dynamic.add((obj, site))
        elif kind == "export_registered":
            exports.add(site)
        elif kind in ("duplicate_candidate", "canonical_anomaly", "identity_failure",
                      "qi_passthrough", "unwrapped_object", "unwrapped_root",
                      "identity_mismatch", "return_passthrough", "returned_untracked",
                      "root_wrapper_rejected"):
            anomalies.append({"kind": kind, "site": site, "object": obj, "related": related})
    return {"kinds": dict(kinds), "inlinePeak": peak, "inlineObservedTargets": inline_sites,
            "iatDistinctWrites": len({slot for owner, slot, site in iat}),
            "iatDistinctWriteRoutes": len(iat), "iatWrites": sorted(iat),
            "dynamicRoutes": sorted(dynamic), "exportRegistrations": sorted(exports),
            "anomalies": anomalies,
            "notes": "IAT count is distinct writes observed, not a live-slot count after unload. "
                     "Export registrations are not EAT patches. COM calls are excluded."}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sample", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--bin", required=True)
    p.add_argument("--agility")
    p.add_argument("--modes", nargs="+", default=["single", "second", "resize", "agility",
                            "agility-preload", "agility-second", "factory-root"],
                   choices=["single", "second", "resize", "agility", "agility-preload", "agility-second", "factory-root", "getdevice-probe"])
    a = p.parse_args()
    root = Path(a.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    binary = Path(a.bin).resolve()
    report = {"coreSHA256": hashlib.sha256((binary / "dgcore.dll").read_bytes()).hexdigest(),
              "sampleSHA256": hashlib.sha256(Path(a.sample).read_bytes()).hexdigest(),
              "abMode": os.environ.get("DCOMP_DX_CLOSURE_AB", ""), "runs": {}}
    for mode in a.modes:
        for diag in (0, 1):
            case = root / (mode + "-" + str(diag))
            case.mkdir()
            if mode.startswith("agility") and not a.agility:
                report["runs"][case.name] = {"status": "skipped-no-sdk"}
                continue
            env = os.environ.copy()
            env["DCOMP_DX_CLOSURE"] = str(diag)
            env["DCOMP_DX_CLOSURE_LOG"] = str(case / "coverage")
            cmd = [str(binary / "dgcorecmd.exe"), "capture", "-w", "-c", str(case / "frame"),
                   str(Path(a.sample).resolve()), mode, str(case / "frame")]
            if mode.startswith("agility"):
                cmd.append(a.agility)
            started = time.monotonic()
            r = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=60)
            (case / "stdout.log").write_bytes(r.stdout)
            captures = sorted(str(c) for c in case.glob("*.rdc"))
            text = r.stdout.decode(errors="replace")
            status = "captured" if len(captures) == 2 else "capture-failed"
            if "SKIP" in text:
                status = "sdk-path-rejected"
            if "watchdog" in text:
                status = "sample-timeout"
            identities = dict(re.findall(r"identity site=(\S+) equal=([01])", text))
            stress = re.findall(r"mismatches=(\d+)", text)
            closed = bool(identities and stress) and all(v == "1" for v in identities.values()) and all(v == "0" for v in stress)
            item = {"status": status, "identityChecks": identities, "stressMismatches": stress,
                    "closureCorrect": closed, "launcherExit": r.returncode,
                    "elapsed": time.monotonic() - started,
                    "captures": captures,
                    "diagnostics": {f.name: inventory(f) for f in case.glob("coverage.*.log")}}
            report["runs"][case.name] = item
            if captures:
                job = {"captures": captures, "output": str(case / "replay.json")}
                (case / "job.json").write_text(json.dumps(job))
                env["CLOSURE_JOB"] = str(case / "job.json")
                env["DCOMP_DX_CLOSURE"] = "0"
                r = subprocess.run([str(binary / "dgcoreui.exe"), "--python",
                                    str(Path(__file__).with_name("replay_worker.py").resolve())],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
                (case / "replay.log").write_bytes(r.stdout)
                if Path(job["output"]).exists():
                    item["replay"] = json.loads(Path(job["output"]).read_text())
                else:
                    item["replay"] = {"status": "missing-result", "exit": r.returncode}
            (root / "results.json").write_text(json.dumps(report, indent=2))
    report["comparisons"] = {}
    for mode in a.modes:
        lhs = report["runs"][mode + "-0"].get("replay", {})
        rhs = report["runs"][mode + "-1"].get("replay", {})
        left, right = list(lhs.values()), list(rhs.values())
        valid = (report["runs"][mode + "-0"].get("closureCorrect", False) and
                 report["runs"][mode + "-1"].get("closureCorrect", False) and len(left) == len(right) == 2 and
                 all(isinstance(v, dict) and v.get("status") == "replayed" for v in left + right))
        report["comparisons"][mode] = {"valid": valid, "equal": valid and left == right}
    (root / "results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["comparisons"], indent=2))


if __name__ == "__main__":
    main()
