import json
import os
import subprocess
import tempfile
import time

from .glb_validation import validate_glb_bytes


def validate_path(path):
    path = os.path.abspath(path)
    if os.path.isdir(path):
        manifest_path = os.path.join(path, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise ValueError("Evidence package has no manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as stream:
            manifest = json.load(stream)
        if manifest.get("kind") != "draw-evidence-package":
            raise ValueError("Directory is not a Draw Evidence Package")
        glbs = [
            os.path.join(path, "geometry", name)
            for name in ("input.glb", "post_vs.glb")
            if os.path.isfile(os.path.join(path, "geometry", name))
        ]
    else:
        manifest = None
        glbs = [path]
    if not glbs:
        raise ValueError("No GLB files were found")

    files = []
    for glb in glbs:
        with open(glb, "rb") as stream:
            data = stream.read()
        errors = validate_glb_bytes(data)
        files.append(
            {
                "path": glb,
                "byteLength": len(data),
                "status": "pass" if not errors else "failed",
                "errors": errors,
            }
        )
    return {
        "schemaVersion": 1,
        "kind": "draw-package-validation",
        "status": "pass" if all(item["status"] == "pass" for item in files) else "failed",
        "package": path if manifest is not None else None,
        "files": files,
    }


def convert_to_fbx(blender, source_glb, output_fbx, timeout_seconds=300):
    blender = os.path.abspath(blender)
    source_glb = os.path.abspath(source_glb)
    output_fbx = os.path.abspath(output_fbx)
    if not os.path.isfile(blender):
        raise ValueError("Blender executable does not exist: " + blender)
    validation = validate_path(source_glb)
    if validation["status"] != "pass":
        raise ValueError("Input GLB is invalid")
    if os.path.exists(output_fbx):
        raise FileExistsError("Refusing to overwrite existing output: " + output_fbx)
    os.makedirs(os.path.dirname(output_fbx), exist_ok=True)

    script = os.path.join(os.path.dirname(__file__), "blender_convert.py")
    staging_directory = tempfile.mkdtemp(
        prefix=".fbx-convert-", dir=os.path.dirname(output_fbx)
    )
    staging_output = os.path.join(staging_directory, os.path.basename(output_fbx))
    command = [
        blender,
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--python",
        script,
        "--",
        source_glb,
        staging_output,
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1, int(timeout_seconds)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except subprocess.TimeoutExpired as exception:
        raise RuntimeError(
            "Blender conversion exceeded {} seconds".format(timeout_seconds)
        ) from exception
    if completed.returncode != 0 or not os.path.isfile(staging_output):
        details = (completed.stdout + b"\n" + completed.stderr).decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(
            "Blender conversion failed with exit code {}:\n{}".format(
                completed.returncode, details[-12000:]
            )
        )
    os.replace(staging_output, output_fbx)
    try:
        os.rmdir(staging_directory)
    except OSError:
        pass
    return {
        "schemaVersion": 1,
        "kind": "draw-package-conversion-result",
        "status": "succeeded",
        "source": source_glb,
        "output": output_fbx,
        "outputByteLength": os.path.getsize(output_fbx),
        "durationMs": int((time.monotonic() - started) * 1000),
        "converter": "Blender background FBX exporter",
    }
