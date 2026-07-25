import hashlib
import json
import os
import traceback

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import atomic_write_json, enum_name, resource_id, sha256_file, utc_now
from .replay import analyse_capture


STAGES = (
    "Vertex",
    "Hull",
    "Domain",
    "Geometry",
    "Pixel",
    "Compute",
    "Task",
    "Mesh",
    "RayGen",
    "Intersection",
    "AnyHit",
    "ClosestHit",
    "Miss",
    "Callable",
)


def _find_action(actions, event_id):
    for action in actions:
        if int(action.eventId) == int(event_id):
            return action
        found = _find_action(action.children, event_id)
        if found is not None:
            return found
    return None


def _find_resource(controller, identifier, kind):
    values = controller.GetBuffers() if kind == "buffer" else controller.GetTextures()
    for value in values:
        if resource_id(value.resourceId) == identifier:
            return value
    raise ValueError("No {} exists with resourceId {}".format(kind, identifier))


def _descriptor(value):
    if value is None:
        return None
    fmt = getattr(value, "format", None)
    return {
        "resourceId": resource_id(getattr(value, "resource", None)),
        "secondaryResourceId": resource_id(getattr(value, "secondary", None)),
        "type": enum_name(getattr(value, "type", None)),
        "format": str(fmt.Name()) if fmt is not None else None,
        "byteOffset": int(getattr(value, "byteOffset", 0)),
        "byteSize": int(getattr(value, "byteSize", 0)),
        "firstMip": int(getattr(value, "firstMip", 0)),
        "numMips": int(getattr(value, "numMips", 0)),
        "firstSlice": int(getattr(value, "firstSlice", 0)),
        "numSlices": int(getattr(value, "numSlices", 0)),
    }


def _signature(value):
    return {
        "name": str(getattr(value, "varName", "")),
        "semantic": str(getattr(value, "semanticIdxName", "")),
        "semanticIndex": int(getattr(value, "semanticIndex", 0)),
        "registerIndex": int(getattr(value, "regIndex", 0)),
        "systemValue": enum_name(getattr(value, "systemValue", None)),
        "componentType": enum_name(getattr(value, "varType", None)),
        "componentCount": int(getattr(value, "compCount", 0)),
    }


def _reflection(value):
    if value is None:
        return {"status": "unknown", "reason": "Shader reflection is unavailable"}
    return {
        "status": "confirmed",
        "inputSignature": [_signature(item) for item in value.inputSignature],
        "outputSignature": [_signature(item) for item in value.outputSignature],
        "constantBlocks": [
            {
                "name": str(item.name),
                "byteSize": int(item.byteSize),
                "bindArraySize": int(item.bindArraySize),
                "bufferBacked": bool(item.bufferBacked),
            }
            for item in value.constantBlocks
        ],
        "readOnlyResources": [
            {"name": str(item.name), "bindArraySize": int(item.bindArraySize)}
            for item in value.readOnlyResources
        ],
        "readWriteResources": [
            {"name": str(item.name), "bindArraySize": int(item.bindArraySize)}
            for item in value.readWriteResources
        ],
        "samplers": [
            {"name": str(item.name), "bindArraySize": int(item.bindArraySize)}
            for item in value.samplers
        ],
    }


def _set_event(controller, event_id):
    action = _find_action(controller.GetRootActions(), event_id)
    if action is None:
        raise ValueError("No action exists at EID {}".format(event_id))
    controller.SetFrameEvent(int(event_id), True)
    return action


def _pipeline_query(rd, controller, parameters):
    event_id = int(parameters["eventId"])
    _set_event(controller, event_id)
    pipe = controller.GetPipelineState()
    shaders = []
    for stage_name in STAGES:
        stage = getattr(rd.ShaderStage, stage_name, None)
        if stage is None:
            continue
        shader = pipe.GetShader(stage)
        identifier = resource_id(shader)
        if identifier:
            shaders.append(
                {
                    "stage": stage_name,
                    "resourceId": identifier,
                    "entryPoint": str(pipe.GetShaderEntryPoint(stage)),
                }
            )
    result = {
        "eventId": event_id,
        "api": enum_name(controller.GetAPIProperties().pipelineType),
        "graphicsPipelineObject": resource_id(pipe.GetGraphicsPipelineObject()),
        "computePipelineObject": resource_id(pipe.GetComputePipelineObject()),
        "primitiveTopology": enum_name(pipe.GetPrimitiveTopology()),
        "shaders": shaders,
        "outputTargets": [_descriptor(item) for item in pipe.GetOutputTargets()],
        "depthTarget": _descriptor(pipe.GetDepthTarget()),
    }
    if result["api"] == "D3D12":
        state = controller.GetD3D12PipelineState()
        result["d3d12"] = {
            "pipelineResourceId": resource_id(state.pipelineResourceId),
            "rootSignatureResourceId": resource_id(state.rootSignature.resourceId),
            "rootParameterCount": len(state.rootSignature.parameters),
            "staticSamplerCount": len(state.rootSignature.staticSamplers),
            "descriptorHeaps": [resource_id(item) for item in state.descriptorHeaps],
            "resourceStateCount": len(state.resourceStates),
        }
    return result


def _shader_query(rd, controller, parameters):
    event_id = int(parameters["eventId"])
    _set_event(controller, event_id)
    stage_name = str(parameters["stage"])
    if stage_name not in STAGES or not hasattr(rd.ShaderStage, stage_name):
        raise ValueError("Unknown shader stage: " + stage_name)
    stage = getattr(rd.ShaderStage, stage_name)
    pipe = controller.GetPipelineState()
    shader = pipe.GetShader(stage)
    identifier = resource_id(shader)
    if identifier is None:
        raise ValueError("{} shader is not bound at EID {}".format(stage_name, event_id))
    reflection = pipe.GetShaderReflection(stage)
    result = {
        "eventId": event_id,
        "stage": stage_name,
        "resourceId": identifier,
        "entryPoint": str(pipe.GetShaderEntryPoint(stage)),
        "reflection": _reflection(reflection),
    }
    if parameters.get("includeDisassembly", False):
        pipeline = (
            pipe.GetComputePipelineObject()
            if stage_name in ("Compute", "Task", "Mesh", "RayGen")
            else pipe.GetGraphicsPipelineObject()
        )
        disassembly = (
            str(controller.DisassembleShader(pipeline, reflection, ""))
            if reflection is not None
            else ""
        )
        encoded = disassembly.encode("utf-8")
        result["disassembly"] = disassembly[:4 * 1024 * 1024]
        result["disassemblySHA256"] = hashlib.sha256(encoded).hexdigest().upper()
        result["rawContainerStatus"] = "unknown-public-api-not-exposed"
    return result


def _buffer_query(controller, parameters, artifact_directory, max_resource_bytes):
    identifier = str(parameters["resourceId"])
    buffer = _find_resource(controller, identifier, "buffer")
    offset = int(parameters.get("offset", 0))
    if offset < 0 or offset > int(buffer.length):
        raise ValueError("Buffer offset is outside the resource")
    available = int(buffer.length) - offset
    length = int(parameters.get("length", min(available, max_resource_bytes)))
    if length < 0 or length > available or length > max_resource_bytes:
        raise ValueError("Buffer length is outside the resource or service limit")
    data = bytes(controller.GetBufferData(buffer.resourceId, offset, length))
    os.makedirs(artifact_directory, exist_ok=True)
    path = os.path.join(
        artifact_directory,
        "{}_{}_{}.bin".format(identifier.replace(":", "_"), offset, len(data)),
    )
    with open(path, "wb") as stream:
        stream.write(data)
    return {
        "resourceId": identifier,
        "offset": offset,
        "byteLength": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "file": path,
    }


def _texture_query(
    rd, controller, parameters, artifact_directory, max_resource_bytes
):
    identifier = str(parameters["resourceId"])
    texture = _find_resource(controller, identifier, "texture")
    if int(texture.byteSize) > max_resource_bytes:
        raise ValueError("Texture exceeds the service maxResourceBytes limit")
    file_type = str(parameters.get("fileType", "PNG")).upper()
    if file_type not in ("PNG", "DDS", "EXR"):
        raise ValueError("fileType must be PNG, DDS, or EXR")
    save = rd.TextureSave()
    save.resourceId = texture.resourceId
    save.destType = getattr(rd.FileType, file_type)
    save.mip = int(parameters.get("mip", 0))
    save.slice.sliceIndex = int(parameters.get("slice", 0))
    save.sample.sampleIndex = int(parameters.get("sample", 0))
    os.makedirs(artifact_directory, exist_ok=True)
    path = os.path.join(
        artifact_directory, "{}.{}".format(identifier.replace(":", "_"), file_type.lower())
    )
    result = controller.SaveTexture(save, path)
    if not os.path.isfile(path):
        raise RuntimeError("SaveTexture failed: {}".format(result))
    return {
        "resourceId": identifier,
        "fileType": file_type,
        "mip": save.mip,
        "slice": save.slice.sliceIndex,
        "sample": save.sample.sampleIndex,
        "byteLength": os.path.getsize(path),
        "sha256": sha256_file(path),
        "file": path,
    }


def _postvs_query(rd, controller, parameters, artifact_directory, max_resource_bytes):
    event_id = int(parameters["eventId"])
    _set_event(controller, event_id)
    stage_name = str(parameters.get("stage", "VSOut"))
    if not hasattr(rd.MeshDataStage, stage_name):
        raise ValueError("Unknown MeshDataStage: " + stage_name)
    mesh = controller.GetPostVSData(
        int(parameters.get("instance", 0)),
        int(parameters.get("view", 0)),
        getattr(rd.MeshDataStage, stage_name),
    )
    os.makedirs(artifact_directory, exist_ok=True)
    result = {
        "eventId": event_id,
        "stage": stage_name,
        "vertexResourceId": resource_id(mesh.vertexResourceId),
        "vertexByteOffset": int(mesh.vertexByteOffset),
        "vertexByteStride": int(mesh.vertexByteStride),
        "indexResourceId": resource_id(mesh.indexResourceId),
        "indexByteOffset": int(mesh.indexByteOffset),
        "indexByteStride": int(mesh.indexByteStride),
        "baseVertex": int(mesh.baseVertex),
        "numIndices": int(mesh.numIndices),
        "topology": enum_name(mesh.topology),
    }
    vertex_length = min(
        max_resource_bytes,
        int(mesh.vertexByteOffset)
        + int(mesh.vertexByteStride) * max(0, int(mesh.numIndices)),
    )
    if result["vertexResourceId"] and vertex_length:
        data = bytes(controller.GetBufferData(mesh.vertexResourceId, 0, vertex_length))
        path = os.path.join(artifact_directory, "postvs-vertices.bin")
        with open(path, "wb") as stream:
            stream.write(data)
        result["vertexData"] = {
            "file": path,
            "byteLength": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }
    index_length = int(mesh.indexByteStride) * max(0, int(mesh.numIndices))
    if result["indexResourceId"] and 0 < index_length <= max_resource_bytes:
        data = bytes(
            controller.GetBufferData(
                mesh.indexResourceId, int(mesh.indexByteOffset), index_length
            )
        )
        path = os.path.join(artifact_directory, "postvs-indices.bin")
        with open(path, "wb") as stream:
            stream.write(data)
        result["indexData"] = {
            "file": path,
            "byteLength": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }
    return result


def _evidence_query(rd, controller, job):
    evidence_root = os.environ.get("RDX_EVIDENCE_ROOT")
    if not evidence_root or not os.path.isdir(evidence_root):
        raise RuntimeError("Draw Evidence Package tool is unavailable")
    import sys

    if evidence_root not in sys.path:
        sys.path.insert(0, evidence_root)
    from analysis_suite_evidence.exporter import export_action_evidence

    return export_action_evidence(
        rd,
        controller,
        job["capturePath"],
        int(job["parameters"]["eventId"]),
        job["artifactDirectory"],
        int(job["parameters"].get("instance", 0)),
        int(job["maxResourceBytes"]),
    )


def run_job(job):
    import renderdoc as rd

    operation = job["operation"]
    if operation == "analyse_capture":
        return analyse_capture(job["capturePath"])

    capture = rd.OpenCaptureFile()
    controller = None
    try:
        result = capture.OpenFile(job["capturePath"], "", None)
        if result != rd.ResultCode.Succeeded:
            raise RuntimeError("OpenFile failed: {}".format(result))
        result, controller = capture.OpenCapture(rd.ReplayOptions(), None)
        if result != rd.ResultCode.Succeeded or controller is None:
            raise RuntimeError("OpenCapture failed: {}".format(result))
        parameters = job.get("parameters", {})
        if operation == "get_pipeline_state":
            return _pipeline_query(rd, controller, parameters)
        if operation in ("get_shader", "get_shader_reflection"):
            request = dict(parameters)
            request["includeDisassembly"] = operation == "get_shader"
            return _shader_query(rd, controller, request)
        if operation == "get_buffer_data":
            return _buffer_query(
                controller,
                parameters,
                job["artifactDirectory"],
                int(job["maxResourceBytes"]),
            )
        if operation == "save_texture":
            return _texture_query(
                rd,
                controller,
                parameters,
                job["artifactDirectory"],
                int(job["maxResourceBytes"]),
            )
        if operation == "get_post_vs_data":
            return _postvs_query(
                rd,
                controller,
                parameters,
                job["artifactDirectory"],
                int(job["maxResourceBytes"]),
            )
        if operation == "export_action_evidence":
            return _evidence_query(rd, controller, job)
        raise ValueError("Unknown query operation: " + operation)
    finally:
        if controller is not None:
            controller.Shutdown()
        capture.Shutdown()


def main():
    job_path = os.environ.get("RDX_QUERY_JOB")
    if not job_path:
        raise RuntimeError("RDX_QUERY_JOB is not set")
    with open(job_path, "r", encoding="utf-8") as stream:
        job = json.load(stream)
    base = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rdx-query-result",
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "operation": job.get("operation"),
        "capturePath": os.path.abspath(job.get("capturePath", "")),
        "captureSHA256": job.get("captureSHA256"),
    }
    try:
        payload = run_job(job)
        base.update({"status": "succeeded", "payload": payload})
    except BaseException as exception:
        base.update(
            {
                "status": "failed",
                "error": {
                    "type": type(exception).__name__,
                    "message": str(exception),
                    "traceback": traceback.format_exc()[-16384:],
                },
            }
        )
    atomic_write_json(job["resultPath"], base)
