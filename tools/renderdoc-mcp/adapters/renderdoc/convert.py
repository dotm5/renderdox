"""Python 3.6-compatible conversion. Native objects never leave the worker."""
import hashlib
import math
import os
import uuid


def rid(value):
    if value is None:
        return None
    text = str(value)
    return None if text in ("ResourceId::0", "0", "None") else text


def enum(value, enum_type=None):
    if enum_type is not None:
        for name in dir(enum_type):
            if name.startswith("_"):
                continue
            member = getattr(enum_type, name)
            if isinstance(member, int) and member == value:
                return name
    return str(value).rsplit(".", 1)[-1] if value is not None else None


def flags(value, enum_type):
    return "|".join(name for name in dir(enum_type) if not name.startswith("_")
                    and isinstance(getattr(enum_type, name), int)
                    and getattr(enum_type, name) > 0
                    and getattr(enum_type, name) & (getattr(enum_type, name) - 1) == 0
                    and value & getattr(enum_type, name))


def plain(value, depth=0):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (bytes, bytearray)):
        return {"byteLength": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if depth > 12:
        return {"unavailable": "nested object exceeds conversion depth", "type": type(value).__name__}
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if type(value).__name__ == "ResourceId":
        return rid(value)
    if isinstance(value, (list, tuple)) or type(value).__name__.startswith(("rdcarray", "rdcfixedarray")):
        return [plain(v, depth + 1) for v in value]
    fields = {}
    for key in dir(value):
        if key.startswith("_") or key in ("this", "thisown"):
            continue
        try:
            item = getattr(value, key)
            if not callable(item):
                fields[key] = plain(item, depth + 1)
        except (AttributeError, TypeError):
            pass
    return fields if fields else enum(value)


def artifact(directory, data, extension="bin", **metadata):
    identifier = "artifact-" + uuid.uuid4().hex
    path = os.path.join(directory, identifier + "." + extension)
    os.makedirs(directory, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(path, "wb") as stream:
        stream.write(data)
    result = {"artifactId": identifier, "path": path, "byteLength": len(data),
              "sha256": hashlib.sha256(data).hexdigest()}
    result.update(metadata)
    return result


def status_ok(rd, result):
    return result == rd.ResultCode.Succeeded
