import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path, block_size=4 * 1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def structural_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def enum_name(value):
    if value is None:
        return None
    text = str(value)
    if "." in text:
        return text.rsplit(".", 1)[-1]
    return text


def resource_id(value):
    if value is None:
        return None
    text = str(value)
    if text in ("ResourceId::0", "0", "None"):
        return None
    return text


def atomic_write_text(path, text):
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
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
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def bounded_text(value, maximum=16384):
    text = "" if value is None else str(value)
    if len(text) <= maximum:
        return text
    return text[:maximum] + "\n...[truncated]"
