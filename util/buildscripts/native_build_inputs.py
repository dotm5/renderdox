#!/usr/bin/env python3
"""Fingerprint native inputs independently of MCP packaging-only commits.

The digest intentionally omits HEAD: a reused native binary keeps the Git commit
embedded by its original build. The release merger records that producer commit
separately from the commit assembling the current MCP package.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


EXCLUDED_PREFIXES = (
    "tools/renderdoc-mcp/",
    "docs/",
    "assets/readme/",
    ".github/workflows/",
)


def is_native_input(path):
    return not path.startswith(EXCLUDED_PREFIXES)


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments])


def fingerprint(repository, profile):
    if not isinstance(profile, dict):
        raise ValueError("The native build profile must be a JSON object")
    source_commit = git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    dirty = git(repository, "diff", "--name-only", "-z", "HEAD").decode(
        "utf-8", errors="surrogateescape"
    )
    changed = [path for path in dirty.split("\0") if path and is_native_input(path)]
    if changed:
        raise ValueError("Native inputs differ from HEAD: " + ", ".join(changed))

    entries = []
    tree = git(repository, "ls-tree", "-r", "-z", "HEAD")
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if is_native_input(path):
            mode, kind, object_id = metadata.decode("ascii").split()
            # Gitlink object IDs also invalidate the cache on submodule updates.
            entries.append([path, mode, kind, object_id])
    if not entries:
        raise ValueError("No tracked native inputs were found")
    payload = {
        "schema_version": 1,
        "excluded_prefixes": EXCLUDED_PREFIXES,
        "native_build_profile": profile,
        "entries": entries,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "source_commit": source_commit,
        "native_inputs_digest": hashlib.sha256(encoded).hexdigest(),
        "native_build_profile": profile,
        "tracked_input_count": len(entries),
        "excluded_prefixes": list(EXCLUDED_PREFIXES),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--profile-json", required=True, help="Native build policy as a JSON object")
    parser.add_argument("--output", required=True, type=Path, help="Write native input metadata JSON")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"), type=Path)
    args = parser.parse_args()
    try:
        report = fingerprint(args.repository, json.loads(args.profile_json))
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write("native-inputs-digest=" + report["native_inputs_digest"] + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
