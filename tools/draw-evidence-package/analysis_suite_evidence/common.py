import hashlib
import json
import os
import tempfile


SCHEMA_VERSION = 1
TOOL_VERSION = "1.0.0"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_write_bytes(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".write-", dir=directory)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path, value):
    data = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ).encode("utf-8")
    atomic_write_bytes(path, data + b"\n")


def resource_id(value):
    if value is None:
        return None
    text = str(value)
    if text in ("", "ResourceId::0", "0"):
        return None
    return text


def enum_name(value):
    if value is None:
        return "Unknown"
    try:
        return str(value).split(".")[-1]
    except Exception:
        return "Unknown"


def result_code(value):
    return enum_name(getattr(value, "code", value))


def safe_name(value):
    text = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in str(value)
    )
    text = text.strip("._")
    return text[:96] or "unnamed"


def bytes_record(data, include_preview=True):
    raw = bytes(data)
    result = {"byteLength": len(raw), "sha256": sha256_bytes(raw)}
    if include_preview:
        result["hexPreview"] = raw[:64].hex().upper()
    return result
