import json
import math
import struct


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _align4(data, fill=b"\x00"):
    return data + fill * ((4 - len(data) % 4) % 4)


def _component_type(values):
    maximum = max(values) if values else 0
    return (5123, "H") if maximum <= 65535 else (5125, "I")


def _accessor_type(width):
    return {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}[width]


def build_glb(attributes, indices, mode=4, extras=None):
    if "POSITION" not in attributes:
        raise ValueError("POSITION is required for a mesh GLB")
    vertex_count = len(attributes["POSITION"])
    if vertex_count == 0:
        raise ValueError("At least one vertex is required")
    if any(len(values) != vertex_count for values in attributes.values()):
        raise ValueError("All attributes must contain the same number of vertices")
    if any(index < 0 or index >= vertex_count for index in indices):
        raise ValueError("An index is outside the exported vertex range")

    binary = bytearray()
    buffer_views = []
    accessors = []
    primitive_attributes = {}

    def append_view(payload, target):
        offset = len(binary)
        binary.extend(payload)
        while len(binary) % 4:
            binary.append(0)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(payload),
                "target": target,
            }
        )
        return len(buffer_views) - 1

    for semantic in sorted(attributes, key=lambda name: (name != "POSITION", name)):
        values = attributes[semantic]
        width = len(values[0])
        if width not in (1, 2, 3, 4):
            raise ValueError("Unsupported attribute width for {}".format(semantic))
        if any(len(value) != width for value in values):
            raise ValueError("Inconsistent attribute width for {}".format(semantic))
        flat = [float(component) for value in values for component in value]
        payload = struct.pack("<{}f".format(len(flat)), *flat)
        view = append_view(payload, 34962)
        accessor = {
            "bufferView": view,
            "byteOffset": 0,
            "componentType": 5126,
            "count": vertex_count,
            "type": _accessor_type(width),
        }
        if semantic == "POSITION":
            accessor["min"] = [
                min(float(value[component]) for value in values)
                for component in range(width)
            ]
            accessor["max"] = [
                max(float(value[component]) for value in values)
                for component in range(width)
            ]
        accessors.append(accessor)
        primitive_attributes[semantic] = len(accessors) - 1

    component_type, format_character = _component_type(indices)
    index_payload = struct.pack(
        "<{}{}".format(len(indices), format_character), *indices
    )
    index_view = append_view(index_payload, 34963)
    accessors.append(
        {
            "bufferView": index_view,
            "byteOffset": 0,
            "componentType": component_type,
            "count": len(indices),
            "type": "SCALAR",
            "min": [min(indices) if indices else 0],
            "max": [max(indices) if indices else 0],
        }
    )

    primitive = {
        "attributes": primitive_attributes,
        "indices": len(accessors) - 1,
        "mode": int(mode),
    }
    if extras:
        primitive["extras"] = extras
    document = {
        "asset": {"version": "2.0", "generator": "RenderDoc Draw Evidence 1.0.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [primitive]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }

    json_payload = _align4(
        json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        b" ",
    )
    binary_payload = _align4(bytes(binary))
    length = 12 + 8 + len(json_payload) + 8 + len(binary_payload)
    return (
        struct.pack("<III", GLB_MAGIC, 2, length)
        + struct.pack("<II", len(json_payload), JSON_CHUNK)
        + json_payload
        + struct.pack("<II", len(binary_payload), BIN_CHUNK)
        + binary_payload
    )


def validate_glb_bytes(data):
    errors = []
    if len(data) < 28:
        return ["GLB is shorter than the mandatory header and chunks"]
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        errors.append("Invalid GLB magic")
    if version != 2:
        errors.append("GLB version is not 2")
    if total_length != len(data):
        errors.append("GLB total length does not match file length")
    offset = 12
    chunks = []
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if offset + length > len(data):
            errors.append("Chunk extends past end of GLB")
            break
        chunks.append((kind, data[offset : offset + length]))
        offset += length
    if offset != len(data):
        errors.append("Trailing or truncated chunk bytes")
    if not chunks or chunks[0][0] != JSON_CHUNK:
        errors.append("First chunk is not JSON")
        return errors
    try:
        document = json.loads(chunks[0][1].decode("utf-8").rstrip(" \x00"))
    except Exception as exception:
        errors.append("Invalid JSON chunk: {}".format(exception))
        return errors
    binary_length = len(chunks[1][1]) if len(chunks) > 1 and chunks[1][0] == BIN_CHUNK else 0
    declared = int(document.get("buffers", [{}])[0].get("byteLength", 0))
    if declared > binary_length:
        errors.append("Declared buffer is larger than BIN chunk")
    for view in document.get("bufferViews", []):
        end = int(view.get("byteOffset", 0)) + int(view.get("byteLength", 0))
        if end > declared:
            errors.append("A bufferView extends past the declared buffer")
    for accessor in document.get("accessors", []):
        count = int(accessor.get("count", 0))
        if count < 0:
            errors.append("Accessor count is negative")
        values = accessor.get("min", []) + accessor.get("max", [])
        if any(not math.isfinite(float(value)) for value in values):
            errors.append("Accessor bounds contain non-finite values")
    return errors
