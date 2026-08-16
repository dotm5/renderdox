#!/usr/bin/env python3
"""Inventory the perceptual colour families used by the legacy PNG icon set."""

from __future__ import annotations

import colorsys
import json
from collections import Counter
from pathlib import Path

from PIL import Image


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RESOURCES = REPO / "qrenderdoc" / "Resources"
REPORT = REPO / "artifacts" / "icon-modernization" / "v3" / "legacy_color_audit.json"


def hue_family(red: int, green: int, blue: int) -> str:
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    if saturation < 0.18 or value < 0.14:
        return "neutral"
    degrees = hue * 360
    if degrees < 18 or degrees >= 345:
        return "red"
    if degrees < 45:
        return "orange"
    if degrees < 70:
        return "yellow"
    if degrees < 165:
        return "green"
    if degrees < 195:
        return "cyan"
    if degrees < 255:
        return "blue"
    if degrees < 300:
        return "purple"
    return "magenta"


def audit(path: Path) -> dict[str, object]:
    image = Image.open(path).convert("RGBA")
    families: Counter[str] = Counter()
    opaque_pixels = []
    for red, green, blue, alpha in image.getdata():
        if alpha < 48:
            continue
        weight = max(1, round(alpha / 64))
        families[hue_family(red, green, blue)] += weight
        opaque_pixels.append((red, green, blue))

    quantized = Image.new("RGB", (len(opaque_pixels), 1))
    quantized.putdata(opaque_pixels)
    quantized = quantized.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    dominant = []
    for count, index in sorted(quantized.getcolors() or [], reverse=True):
        red, green, blue = palette[index * 3 : index * 3 + 3]
        dominant.append({"hex": f"#{red:02X}{green:02X}{blue:02X}", "weight": count})

    total = sum(families.values()) or 1
    ratios = {name: round(count / total, 4) for name, count in families.most_common()}
    chromatic = [name for name, ratio in ratios.items() if name != "neutral" and ratio >= 0.025]
    return {
        "size": list(image.size),
        "hue_ratios": ratios,
        "chromatic_families": chromatic,
        "dominant_quantized_colors": dominant,
    }


def main() -> int:
    manifest = json.loads((HERE / "icon-manifest.json").read_text(encoding="utf-8"))
    icons = []
    for entry in manifest["icons"]:
        name = entry["id"]
        source = RESOURCES / f"{name}@2x.png"
        icons.append({"id": name, "source": source.relative_to(REPO).as_posix(), **audit(source)})

    report = {
        "schema": 1,
        "method": "alpha-weighted HSV family inventory plus eight-colour median-cut quantization",
        "icons": icons,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"audited {len(icons)} legacy icons; report={REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
