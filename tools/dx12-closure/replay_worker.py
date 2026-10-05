"""Run with dgcoreui --python; job and output paths come from CLOSURE_JOB."""
import collections
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import renderdoc as rd


def replay(path):
    cap = rd.OpenCaptureFile()
    ctrl = None
    try:
        opened = cap.OpenFile(path, "", None)
        if opened != rd.ResultCode.Succeeded:
            raise RuntimeError(str(opened))
        status, ctrl = cap.OpenCapture(rd.ReplayOptions(), None)
        if status != rd.ResultCode.Succeeded:
            raise RuntimeError(str(status))
        flat = []

        def visit(items):
            for a in items:
                flat.append(a)
                visit(a.children)
        visit(ctrl.GetRootActions())
        draws = [a for a in flat if a.flags & rd.ActionFlags.Drawcall]
        samples = []
        for a in draws:
            ctrl.SetFrameEvent(a.eventId, True)
            pipe = ctrl.GetPipelineState()
            shaders = {}
            for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Pixel):
                reflection = pipe.GetShaderReflection(stage)
                shaders[str(stage)] = (hashlib.sha256(bytes(reflection.rawBytes)).hexdigest()
                                       if reflection else None)
            outputs = []
            for target in pipe.GetOutputTargets():
                if target.resource == rd.ResourceId.Null():
                    continue
                tex = next(t for t in ctrl.GetTextures() if t.resourceId == target.resource)
                data = bytes(ctrl.GetTextureData(target.resource, rd.Subresource()))
                outputs.append({"width": tex.width, "height": tex.height,
                                "format": tex.format.Name(),
                                "sha256": hashlib.sha256(data).hexdigest()})
            samples.append({"vertices": a.numIndices, "instances": a.numInstances,
                            "shaders": shaders, "outputs": outputs})
        semantic = None
        if os.environ.get("CLOSURE_SEMANTICS") == "1":
            structured = ctrl.GetStructuredFile()
            resources = ctrl.GetResources()
            resource_types = {r.resourceId: str(r.type) for r in resources}
            chunks = collections.Counter(str(c.name) for c in structured.chunks)
            edges = collections.Counter()
            for r in resources:
                for parent in r.parentResources:
                    edges[(str(r.type), resource_types.get(parent, "unlisted"))] += 1
            submits = []

            def fields(node):
                result = []
                if node.type.basetype == rd.SDBasic.Resource:
                    result.append((str(node.name), resource_types.get(node.AsResourceId(), "null-or-unlisted")))
                elif node.type.basetype == rd.SDBasic.UnsignedInteger and str(node.name) in ("Value", "NumCommandLists"):
                    result.append((str(node.name), node.AsInt()))
                for i in range(node.NumChildren()):
                    result.extend(fields(node.GetChild(i)))
                return result

            for c in structured.chunks:
                if any(tag in str(c.name) for tag in ("ExecuteCommandLists", "Signal", "Wait")):
                    submits.append((str(c.name), fields(c)))
            semantic = {"chunks": dict(chunks), "submission": submits,
                        "resolveChunks": {k: v for k, v in chunks.items() if "Resolve" in k},
                        "resourceTypes": dict(collections.Counter(resource_types.values())),
                        "dependencyEdges": sorted((a, b, count) for (a, b), count in edges.items())}
        return {"status": "replayed", "api": str(ctrl.GetAPIProperties().pipelineType),
                "actions": [(str(a.flags), a.numIndices, a.numInstances) for a in flat],
                "draws": samples, "textures": len(ctrl.GetTextures()),
                "buffers": len(ctrl.GetBuffers()),
                "debugMessages": [m.description for m in ctrl.GetDebugMessages()],
                "semantics": semantic}
    finally:
        if ctrl:
            ctrl.Shutdown()
        cap.Shutdown()


def unreal(job):
    opts = rd.CaptureOptions()
    result = rd.ExecuteAndInject(job["exe"], os.path.dirname(job["exe"]),
                                 job.get("args", "-dx12 -windowed -ResX=640 -ResY=360 -nosound -unattended -novsync"),
                                 [], job["capturePrefix"], opts, False)
    if result.result != rd.ResultCode.Succeeded:
        raise RuntimeError(str(result.result))
    target = rd.CreateTargetControl("", result.ident, "DX12 closure probe", False)
    if not target:
        raise RuntimeError("target control unavailable")
    pid = target.GetPID()
    events = []
    start = time.monotonic()
    triggered = False
    if job.get("frame"):
        target.QueueCapture(job["frame"], 1)
        triggered = True
    try:
        while target.Connected() and time.monotonic() - start < 45:
            message = target.ReceiveMessage(None)
            if message.type == rd.TargetControlMessageType.NewCapture:
                events.append(message.newCapture.path)
                break
            if not triggered and time.monotonic() - start > 8:
                target.TriggerCapture(1)
                triggered = True
            time.sleep(0.05)
    finally:
        target.Shutdown()
        # Stop only the PID created by this invocation, never an existing client.
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {"pid": pid, "captures": events, "triggered": triggered}


try:
    with open(os.environ["CLOSURE_JOB"], "r") as f:
        job = json.load(f)
    if job.get("unreal"):
        result = unreal(job)
    else:
        result = {}
        for path in job["captures"]:
            try:
                result[path] = replay(path)
            except Exception:
                result[path] = {"status": "failed", "traceback": traceback.format_exc()}
    with open(job["output"], "w") as f:
        json.dump(result, f, indent=2)
except BaseException:
    traceback.print_exc()
finally:
    sys.exit(0)
