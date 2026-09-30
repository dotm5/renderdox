import hashlib
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

from contracts import ToolError


def numeric_texture(value):
    texture, sub = value["texture"], value["subresource"]
    fmt = texture["format"]
    width, height, depth = (max(1, int(texture[x]) >> int(sub["mip"])) for x in ("width", "height", "depth"))
    raw = Path(value["data"]["path"]).read_bytes()
    kind, component = fmt["type"], fmt["compType"]
    # SWIG enum values are integral on some bindings. formatName is included by
    # the adapter so native enum spelling is also available across versions.
    name = texture["formatName"].upper()
    size, count = int(fmt["compByteWidth"]), int(fmt["compCount"])
    if "R10G10B10A2" in name:
        packed = np.frombuffer(raw, "<u4")
        data = np.stack([(packed >> shift) & mask for shift, mask in [(0, 1023), (10, 1023), (20, 1023), (30, 3)]], axis=-1).astype(np.float64)
        if "UINT" not in name:
            data /= [1023, 1023, 1023, 3]
    elif "R11G11B10" in name:
        packed = np.frombuffer(raw, "<u4")
        channels = []
        for shift, bits in ((0, 6), (11, 6), (22, 5)):
            v = (packed >> shift) & ((1 << (bits + 5)) - 1)
            exponent, mantissa = v >> bits, v & ((1 << bits) - 1)
            channels.append(np.where(exponent == 0, np.ldexp(mantissa.astype(float), 1 - 15 - bits),
                             np.where(exponent == 31, np.where(mantissa == 0, np.inf, np.nan),
                                      np.ldexp(1 + mantissa / (1 << bits), exponent.astype(int) - 15))))
        data = np.stack(channels, -1)
    elif "D24" in name or "R24G8" in name:
        packed = np.frombuffer(raw, "<u4")
        data = np.stack([(packed & 0xffffff) / 16777215.0, (packed >> 24).astype(float)], -1)
    elif "D32" in name and "S8" in name:
        packed = np.frombuffer(raw, dtype=np.dtype([("depth", "<f4"), ("stencil", "u1"), ("pad", "u1", 3)]))
        data = np.stack([packed["depth"], packed["stencil"]], -1)
    elif name.startswith("BC") or "ASTC" in name or "ETC" in name or "YUV" in name:
        raise ToolError("unsupported_numeric_format", name + ": raw artifacts retained; use explicit displayed-image comparison")
    else:
        if size not in (1, 2, 4, 8) or count < 1:
            raise ToolError("unsupported_numeric_format", name)
        if "FLOAT" in name or component == "Float" or ("DEPTH" in name and size == 4):
            dtype = "<f" + str(size)
        elif "SINT" in name or "SNORM" in name or component in ("SInt", "SNorm"):
            dtype = "<i" + str(size)
        else:
            dtype = "<u" + str(size)
        data = np.frombuffer(raw, dtype).reshape(-1, count).astype(np.float64)
        if "UNORM" in name or "SRGB" in name or component in ("UNorm", "UNormSRGB"):
            data /= (2 ** (size * 8) - 1)
        elif "SNORM" in name or component == "SNorm":
            data = np.maximum(-1, data / (2 ** (size * 8 - 1) - 1))
    if data.shape[0] != width * height * depth:
        raise ToolError("unexpected_texture_layout", "Raw byte layout does not match texture dimensions")
    if fmt.get("bgraOrder"):
        data = data[:, [2, 1, 0] + list(range(3, data.shape[-1]))]
    return data.reshape(depth, height, width, -1), {"format": name, "colorSpace": "encoded sRGB" if "SRGB" in name else "native numeric", "width": width, "height": height, "depth": depth}


def image_artifact(directory, pixels, label):
    path = Path(directory) / ("artifact-" + uuid.uuid4().hex + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(path)
    return {"artifactId": path.stem, "path": str(path), "byteLength": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mimeType": "image/png", "role": label}


def compare(left, right, args, directory):
    try:
        a, metadata_a = numeric_texture(left)
        b, metadata_b = numeric_texture(right)
    except ToolError as exc:
        return {"status": "unsupported", "error": exc.payload(), "left": left, "right": right}
    if a.shape != b.shape:
        raise ToolError("incompatible_dimensions", "No implicit resampling", {"left": a.shape, "right": b.shape})
    if metadata_a["format"] != metadata_b["format"]:
        raise ToolError("incompatible_format", "Choose resources with the same numeric interpretation", {"left": metadata_a, "right": metadata_b})
    x0, y0, x1, y1 = 0, 0, a.shape[2], a.shape[1]
    if args.get("roi"):
        x0, y0, x1, y1 = args["roi"]
        if not (0 <= x0 < x1 <= a.shape[2] and 0 <= y0 < y1 <= a.shape[1]):
            raise ToolError("invalid_roi", "ROI must be [x0,y0,x1,y1] within the image")
    channels = args.get("channels", list(range(a.shape[3])))
    aa, bb = a[:, y0:y1, x0:x1, channels], b[:, y0:y1, x0:x1, channels]
    finite = np.isfinite(aa) & np.isfinite(bb)
    delta = np.where(finite, np.abs(aa - bb), 0)
    nonfinite_changed = (~finite) & ~((aa == bb) | (np.isnan(aa) & np.isnan(bb)))
    tolerance = args.get("threshold", 0) + args.get("relativeThreshold", 0) * np.maximum(np.abs(aa), np.abs(bb))
    changed = np.any((delta > tolerance) | nonfinite_changed, axis=-1)
    coords = np.argwhere(changed)
    bounds = None if not len(coords) else {"z0": int(coords[:, 0].min()), "z1": int(coords[:, 0].max()) + 1,
        "x0": int(coords[:, 2].min()) + x0, "x1": int(coords[:, 2].max()) + x0 + 1,
        "y0": int(coords[:, 1].min()) + y0, "y1": int(coords[:, 1].max()) + y0 + 1}
    strength = np.max(delta, -1)
    peak = float(strength.max()) if strength.size else 0
    heat = np.zeros((a.shape[1], a.shape[2], 3), np.uint8)
    # A 3D numeric diff reports the full volume; the preview is the max projection.
    heat[y0:y1, x0:x1, 0] = np.where(changed.any(0), 255, 0)
    heat[y0:y1, x0:x1, 1] = (np.clip(strength.max(0) / (peak or 1), 0, 1) * 180).astype(np.uint8)
    return {"status": "completed", "left": left, "right": right, "numericInterpretation": metadata_a,
            "changedPixels": int(changed.sum()), "comparedPixels": int(changed.size), "changedFraction": float(changed.mean()),
            "boundingBox": bounds, "maxAbsoluteDifference": peak, "meanAbsoluteDifference": float(delta.mean()),
            "nonFiniteChanges": int(nonfinite_changed.sum()), "threshold": args.get("threshold", 0),
            "relativeThreshold": args.get("relativeThreshold", 0), "roi": [x0, y0, x1, y1], "channels": channels,
            "heatmap": image_artifact(directory, heat, "numeric-diff-max-projection"),
            "interpretation": "Difference is observational; no change does not imply no rendered object"}
