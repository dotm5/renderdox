import json
import math
import struct


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def validate_glb_bytes(data):
    errors = []
    if len(data) < 28:
        return ["GLB is shorter than the mandatory header and chunks"]
    magic, version, declared_length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        errors.append("Invalid GLB magic")
    if version != 2:
        errors.append("GLB version is not 2")
    if declared_length != len(data):
        errors.append("GLB total length does not match file length")

    chunks = []
    offset = 12
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

    binary_length = (
        len(chunks[1][1])
        if len(chunks) > 1 and chunks[1][0] == BIN_CHUNK
        else 0
    )
    buffers = document.get("buffers", [])
    declared_buffer = int(buffers[0].get("byteLength", 0)) if buffers else 0
    if declared_buffer > binary_length:
        errors.append("Declared buffer is larger than BIN chunk")
    for view in document.get("bufferViews", []):
        end = int(view.get("byteOffset", 0)) + int(view.get("byteLength", 0))
        if end > declared_buffer:
            errors.append("A bufferView extends past the declared buffer")
    for accessor in document.get("accessors", []):
        if int(accessor.get("count", 0)) < 0:
            errors.append("Accessor count is negative")
        values = accessor.get("min", []) + accessor.get("max", [])
        if any(not math.isfinite(float(value)) for value in values):
            errors.append("Accessor bounds contain non-finite values")
    return errors
