#!/usr/bin/env python3
"""Reconcile the bundle SVG QA with the user-requested legacy colour palette.

The ZIP bundle linter remains unmodified and authoritative for geometry,
forbidden SVG features, stroke widths, and Qt-safe structure. Its fixed palette
is intentionally narrower than the legacy-colour variant requested later by the
user. This validator accepts only those palette diagnostics whose colours are
declared in icon-manifest.json and rejects every other bundle diagnostic.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


PALETTE_ERROR = re.compile(r"^unexpected (?:stroke|fill) color (#[0-9A-Fa-f]{6}) in <[^>]+>$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bundle-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    allowed = {"#000000", "none"}
    allowed.update(value.lower() for value in manifest["legacy_color_palette"].values())

    bundle_report = json.loads(args.bundle_report.read_text(encoding="utf-8"))
    accepted_palette_diagnostics = []
    policy_errors = []
    for item in bundle_report:
        for message in item.get("errors", []):
            match = PALETTE_ERROR.match(message)
            if match and match.group(1).lower() in allowed:
                accepted_palette_diagnostics.append({"file": item["file"], "diagnostic": message})
            else:
                policy_errors.append({"file": item["file"], "diagnostic": message})

    unknown_source_colours = []
    checked = 0
    for path in sorted(args.root.rglob("*.svg")):
        checked += 1
        root = ET.parse(path).getroot()
        for element in root.iter():
            for attribute in ("stroke", "fill"):
                value = element.attrib.get(attribute)
                if value and value.lower() not in allowed:
                    unknown_source_colours.append(
                        {"file": str(path), "attribute": attribute, "value": value}
                    )

    report = {
        "schema": 1,
        "checked_svg_count": checked,
        "allowed_palette": sorted(allowed),
        "bundle_geometry_or_structure_errors": policy_errors,
        "accepted_declared_palette_diagnostics": accepted_palette_diagnostics,
        "unknown_source_colours": unknown_source_colours,
        "passed": not policy_errors and not unknown_source_colours,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"checked {checked} legacy-colour SVGs; "
        f"bundle non-palette errors={len(policy_errors)}; "
        f"unknown colours={len(unknown_source_colours)}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
