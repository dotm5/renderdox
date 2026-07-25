import os
import shutil
import time
import uuid

from .common import (
    SCHEMA_VERSION,
    TOOL_VERSION,
    atomic_write_bytes,
    atomic_write_json,
    bytes_record,
    enum_name,
    resource_id,
    safe_name,
    sha256_bytes,
    sha256_file,
)
from .mesh import export_input_mesh, export_postvs_mesh
from .policy import texture_export_policy


ACTION_FLAG_NAMES = (
    "Clear",
    "Drawcall",
    "Dispatch",
    "MeshDispatch",
    "Present",
    "MultiAction",
    "Copy",
    "Resolve",
    "GenMips",
    "PassBoundary",
    "DispatchRay",
    "BuildAccStruct",
    "Indexed",
    "Instanced",
    "Indirect",
    "BeginPass",
    "EndPass",
)

SHADER_STAGES = (
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


def _contains(flags, value):
    try:
        return bool(flags & value)
    except (TypeError, ValueError):
        try:
            return (int(flags) & int(value)) != 0
        except (TypeError, ValueError):
            return False


def _action_flags(rd, flags):
    result = []
    for name in ACTION_FLAG_NAMES:
        value = getattr(rd.ActionFlags, name, None)
        if value is not None and _contains(flags, value):
            result.append(name)
    return result


def _find_action(actions, event_id):
    for action in actions:
        if int(action.eventId) == int(event_id):
            return action
        found = _find_action(action.children, event_id)
        if found is not None:
            return found
    return None


def _descriptor(value):
    if value is None:
        return None
    fmt = getattr(value, "format", None)
    return {
        "type": enum_name(getattr(value, "type", None)),
        "flags": str(getattr(value, "flags", "")),
        "format": str(fmt.Name()) if fmt is not None else None,
        "componentType": enum_name(getattr(fmt, "compType", None)),
        "resourceId": resource_id(getattr(value, "resource", None)),
        "secondaryResourceId": resource_id(getattr(value, "secondary", None)),
        "viewResourceId": resource_id(getattr(value, "view", None)),
        "byteOffset": int(getattr(value, "byteOffset", 0)),
        "byteSize": int(getattr(value, "byteSize", 0)),
        "counterByteOffset": int(getattr(value, "counterByteOffset", 0)),
        "bufferStructCount": int(getattr(value, "bufferStructCount", 0)),
        "elementByteSize": int(getattr(value, "elementByteSize", 0)),
        "firstSlice": int(getattr(value, "firstSlice", 0)),
        "numSlices": int(getattr(value, "numSlices", 0)),
        "firstMip": int(getattr(value, "firstMip", 0)),
        "numMips": int(getattr(value, "numMips", 0)),
        "textureType": enum_name(getattr(value, "textureType", None)),
        "swizzle": str(getattr(value, "swizzle", "")),
    }


def _used_descriptor(value, stage_name, category):
    access = getattr(value, "access", None)
    return {
        "stage": stage_name,
        "category": category,
        "access": {
            "type": enum_name(getattr(access, "type", None)),
            "index": int(getattr(access, "index", 0)),
            "arrayElement": int(getattr(access, "arrayElement", 0)),
            "descriptorStore": resource_id(getattr(access, "descriptorStore", None)),
            "byteOffset": int(getattr(access, "byteOffset", 0)),
            "byteSize": int(getattr(access, "byteSize", 0)),
            "staticallyUnused": bool(getattr(access, "staticallyUnused", False)),
        },
        "descriptor": _descriptor(getattr(value, "descriptor", None)),
        "sampler": str(getattr(value, "sampler", "")),
    }


def _signature(parameter):
    return {
        "name": str(getattr(parameter, "varName", "")),
        "semantic": str(getattr(parameter, "semanticIdxName", "")),
        "semanticIndex": int(getattr(parameter, "semanticIndex", 0)),
        "registerIndex": int(getattr(parameter, "regIndex", 0)),
        "systemValue": enum_name(getattr(parameter, "systemValue", None)),
        "componentType": enum_name(getattr(parameter, "varType", None)),
        "componentCount": int(getattr(parameter, "compCount", 0)),
        "stream": int(getattr(parameter, "stream", 0)),
    }


def _shader_variable(variable):
    kind = enum_name(getattr(variable, "type", None))
    value = getattr(variable, "value", None)
    values = []
    count = max(1, int(getattr(variable, "rows", 0)) * int(getattr(variable, "columns", 0)))
    field = {
        "Float": "f32v",
        "Double": "f64v",
        "Half": "f16v",
        "SInt": "s32v",
        "UInt": "u32v",
        "SLong": "s64v",
        "ULong": "u64v",
        "Bool": "u32v",
    }.get(kind)
    if field and value is not None:
        try:
            values = [getattr(value, field)[index] for index in range(min(count, 16))]
        except Exception:
            values = []
    return {
        "name": str(getattr(variable, "name", "")),
        "rows": int(getattr(variable, "rows", 0)),
        "columns": int(getattr(variable, "columns", 0)),
        "type": kind,
        "flags": str(getattr(variable, "flags", "")),
        "value": values,
        "members": [_shader_variable(member) for member in getattr(variable, "members", [])],
    }


def _viewport(value):
    if value is None:
        return None
    return {
        "x": float(getattr(value, "x", 0.0)),
        "y": float(getattr(value, "y", 0.0)),
        "width": float(getattr(value, "width", 0.0)),
        "height": float(getattr(value, "height", 0.0)),
        "minDepth": float(getattr(value, "minDepth", 0.0)),
        "maxDepth": float(getattr(value, "maxDepth", 0.0)),
    }


def _scissor(value):
    if value is None:
        return None
    return {
        "x": int(getattr(value, "x", 0)),
        "y": int(getattr(value, "y", 0)),
        "width": int(getattr(value, "width", 0)),
        "height": int(getattr(value, "height", 0)),
        "enabled": bool(getattr(value, "enabled", True)),
    }


def _resource_descriptions(controller):
    descriptions = {}
    for resource in controller.GetResources():
        descriptions[resource_id(resource.resourceId)] = {
            "resourceId": resource_id(resource.resourceId),
            "name": str(resource.name),
            "type": enum_name(resource.type),
            "autogeneratedName": bool(resource.autogeneratedName),
        }
    textures = {}
    for texture in controller.GetTextures():
        identifier = resource_id(texture.resourceId)
        textures[identifier] = {
            "resourceId": identifier,
            "format": str(texture.format.Name()),
            "componentType": enum_name(texture.format.compType),
            "dimension": int(texture.dimension),
            "width": int(texture.width),
            "height": int(texture.height),
            "depth": int(texture.depth),
            "mips": int(texture.mips),
            "arraySize": int(texture.arraysize),
            "samples": int(texture.msSamp),
            "byteSize": int(texture.byteSize),
            "creationFlags": str(texture.creationFlags),
        }
    buffers = {}
    for buffer in controller.GetBuffers():
        identifier = resource_id(buffer.resourceId)
        buffers[identifier] = {
            "resourceId": identifier,
            "length": int(buffer.length),
            "creationFlags": str(buffer.creationFlags),
        }
    return descriptions, textures, buffers


def _write_mesh(stage_directory, name, result):
    glb = result.pop("glb", None)
    raw_vertex_buffers = result.pop("rawVertexBuffers", [])
    raw_index = result.pop("rawIndexBuffer", None)
    if glb is not None:
        atomic_write_bytes(os.path.join(stage_directory, "{}.glb".format(name)), glb)
        result["glb"] = "{}.glb".format(name)
        result["glbSHA256"] = sha256_bytes(glb)
    vertex_directory = os.path.join(stage_directory, "vertex_buffers")
    os.makedirs(vertex_directory, exist_ok=True)
    for index, record in enumerate(raw_vertex_buffers):
        data = record.pop("data")
        filename = "{}_vb_{}.bin".format(name, index)
        atomic_write_bytes(os.path.join(vertex_directory, filename), data)
        record["path"] = "vertex_buffers/{}".format(filename)
    if raw_index is not None:
        data = raw_index.pop("data")
        filename = "{}_index_buffer.bin".format(name)
        atomic_write_bytes(os.path.join(stage_directory, filename), data)
        raw_index["path"] = filename
    result["rawVertexBuffers"] = raw_vertex_buffers
    result["rawIndexBuffer"] = raw_index
    return result


def _shader_documents(
    rd,
    controller,
    pipe,
    action,
    shaders_directory,
    constants_directory,
    max_resource_bytes,
):
    pipeline_object = (
        pipe.GetComputePipelineObject()
        if _contains(action.flags, rd.ActionFlags.Dispatch)
        else pipe.GetGraphicsPipelineObject()
    )
    records = []
    hashes = []
    constant_records = []
    descriptor_records = []
    buffer_lengths = {
        resource_id(item.resourceId): int(item.length) for item in controller.GetBuffers()
    }
    raw_constants_directory = os.path.join(constants_directory, "raw")
    os.makedirs(raw_constants_directory, exist_ok=True)

    for stage_name in SHADER_STAGES:
        stage = getattr(rd.ShaderStage, stage_name, None)
        if stage is None:
            continue
        shader = pipe.GetShader(stage)
        identifier = resource_id(shader)
        if identifier is None:
            continue
        entry = str(pipe.GetShaderEntryPoint(stage))
        reflection = pipe.GetShaderReflection(stage)
        disassembly = ""
        try:
            if reflection is not None:
                disassembly = str(
                    controller.DisassembleShader(pipeline_object, reflection, "")
                )
        except Exception:
            disassembly = ""
        disassembly_data = disassembly.encode("utf-8")
        disassembly_name = "{}.txt".format(stage_name.lower())
        atomic_write_bytes(
            os.path.join(shaders_directory, "disassembly", disassembly_name),
            disassembly_data,
        )
        hashes.append(
            {
                "stage": stage_name,
                "resourceId": identifier,
                "entryPoint": entry,
                "disassemblySHA256": sha256_bytes(disassembly_data),
                "rawBytecodeSHA256": None,
                "rawBytecodeStatus": "unknown-public-api-does-not-expose-original-container",
            }
        )
        reflection_record = {
            "stage": stage_name,
            "resourceId": identifier,
            "entryPoint": entry,
            "inputSignature": [
                _signature(item) for item in getattr(reflection, "inputSignature", [])
            ],
            "outputSignature": [
                _signature(item) for item in getattr(reflection, "outputSignature", [])
            ],
            "constantBlockCount": len(getattr(reflection, "constantBlocks", [])),
            "readOnlyResourceCount": len(
                getattr(reflection, "readOnlyResources", [])
            ),
            "readWriteResourceCount": len(
                getattr(reflection, "readWriteResources", [])
            ),
            "samplerCount": len(getattr(reflection, "samplers", [])),
        }
        records.append(reflection_record)
        atomic_write_json(
            os.path.join(shaders_directory, "raw", "{}.json".format(stage_name.lower())),
            {
                "schemaVersion": SCHEMA_VERSION,
                "stage": stage_name,
                "status": "unknown",
                "reason": "The public Replay API exposes reflection and disassembly but not the exact original DXBC/DXIL/SPIR-V container bytes",
                "resourceId": identifier,
            },
        )

        categories = (
            ("constant", pipe.GetConstantBlocks(stage, False)),
            ("readOnly", pipe.GetReadOnlyResources(stage, False)),
            ("readWrite", pipe.GetReadWriteResources(stage, False)),
            ("sampler", pipe.GetSamplers(stage, False)),
        )
        for category, values in categories:
            for used in values:
                descriptor_records.append(_used_descriptor(used, stage_name, category))

        for block_index, used in enumerate(pipe.GetConstantBlocks(stage, False)):
            descriptor = used.descriptor
            resource = resource_id(descriptor.resource)
            raw_path = None
            raw_record = None
            if resource is not None:
                requested = int(descriptor.byteSize)
                if requested <= 0:
                    requested = max(
                        0,
                        buffer_lengths.get(resource, max_resource_bytes)
                        - int(descriptor.byteOffset),
                    )
                if requested <= max_resource_bytes:
                    data = bytes(
                        controller.GetBufferData(
                            descriptor.resource, int(descriptor.byteOffset), requested
                        )
                    )
                    raw_name = "{}_{}.bin".format(stage_name.lower(), block_index)
                    atomic_write_bytes(os.path.join(raw_constants_directory, raw_name), data)
                    raw_path = "raw/{}".format(raw_name)
                    raw_record = bytes_record(data)
                else:
                    raw_record = {
                        "status": "skipped-limit",
                        "requestedByteLength": requested,
                    }
            variables = []
            try:
                variables = [
                    _shader_variable(variable)
                    for variable in controller.GetCBufferVariableContents(
                        pipeline_object,
                        shader,
                        stage,
                        entry,
                        block_index,
                        descriptor.resource,
                        int(descriptor.byteOffset),
                        int(descriptor.byteSize),
                    )
                ]
            except Exception:
                variables = []
            constant_records.append(
                {
                    "stage": stage_name,
                    "blockIndex": block_index,
                    "resourceId": resource,
                    "descriptor": _descriptor(descriptor),
                    "rawPath": raw_path,
                    "raw": raw_record,
                    "decoded": variables,
                    "decodedFidelity": "exact" if variables else "unknown",
                }
            )
    return records, hashes, descriptor_records, constant_records


def _d3d12_documents(controller):
    state = controller.GetD3D12PipelineState()
    if state is None:
        unavailable = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "not-applicable",
            "reason": "Capture API is not D3D12",
        }
        return unavailable, unavailable, unavailable

    root = state.rootSignature
    parameters = []
    for index, parameter in enumerate(root.parameters):
        constants = bytes(parameter.constants)
        parameters.append(
            {
                "index": index,
                "visibility": str(parameter.visibility),
                "space": int(parameter.space),
                "register": int(parameter.reg),
                "rootConstants": bytes_record(constants),
                "rootConstantsHex": constants.hex().upper(),
                "descriptor": _descriptor(parameter.descriptor),
                "descriptorHeap": resource_id(parameter.heap),
                "descriptorHeapByteOffset": int(parameter.heapByteOffset),
                "tableRanges": [
                    {
                        "category": enum_name(table.category),
                        "space": int(table.space),
                        "baseRegister": int(table.baseRegister),
                        "count": int(table.count),
                        "tableByteOffset": int(table.tableByteOffset),
                        "appended": bool(table.appended),
                    }
                    for table in parameter.tableRanges
                ],
            }
        )
    static_samplers = [
        {
            "visibility": str(sampler.visibility),
            "space": int(sampler.space),
            "register": int(sampler.reg),
            "descriptor": str(sampler.descriptor),
        }
        for sampler in root.staticSamplers
    ]
    root_signature = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "confirmed",
        "resourceId": resource_id(root.resourceId),
        "descriptorHeaps": [resource_id(heap) for heap in state.descriptorHeaps],
        "parameters": parameters,
        "staticSamplers": static_samplers,
    }
    resource_states = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "confirmed",
        "resources": [
            {
                "resourceId": resource_id(resource.resourceId),
                "subresources": [
                    {"index": index, "state": str(item.name)}
                    for index, item in enumerate(resource.states)
                ],
            }
            for resource in state.resourceStates
        ],
    }
    execute_indirect = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "partial",
        "reason": "The public pipeline state exposes child draw parameters but not the full ID3D12CommandSignature declaration",
        "pipelineStateObject": resource_id(state.pipelineResourceId),
        "predication": {
            "resourceId": resource_id(state.predication.resourceId),
            "offset": int(state.predication.offset),
            "skipIfZero": bool(state.predication.skipIfZero),
        },
    }
    return root_signature, resource_states, execute_indirect


def _save_texture(rd, controller, texture, destination, policy):
    texture_save = rd.TextureSave()
    texture_save.resourceId = texture.resourceId
    texture_save.alpha = rd.AlphaMapping.Preserve
    texture_save.mip = -1 if policy["container"] == "DDS" else 0
    texture_save.slice.sliceIndex = -1 if policy["container"] == "DDS" else 0
    if policy["container"] == "RAW":
        data = bytes(controller.GetTextureData(texture.resourceId, rd.Subresource()))
        atomic_write_bytes(destination, data)
        return bytes_record(data)
    texture_save.destType = getattr(rd.FileType, policy["container"])
    controller.SaveTexture(texture_save, destination)
    return {
        "byteLength": os.path.getsize(destination),
        "sha256": sha256_file(destination),
    }


def export_action_evidence(
    rd,
    controller,
    capture_path,
    event_id,
    output_root,
    instance=0,
    max_resource_bytes=256 * 1024 * 1024,
):
    started = time.monotonic()
    action = _find_action(controller.GetRootActions(), event_id)
    if action is None:
        raise ValueError("No action exists at EID {}".format(event_id))
    flags = _action_flags(rd, action.flags)
    if not any(flag in flags for flag in ("Drawcall", "Dispatch", "MeshDispatch", "DispatchRay")):
        raise ValueError("EID {} is not a Draw/Dispatch action".format(event_id))

    controller.SetFrameEvent(int(event_id), True)
    capture_hash = sha256_file(capture_path)
    package_name = "frame_or_draw_{}_{}".format(
        safe_name(os.path.splitext(os.path.basename(capture_path))[0]), int(event_id)
    )
    final_directory = os.path.join(os.path.abspath(output_root), package_name)
    if os.path.exists(final_directory):
        raise FileExistsError("Evidence package already exists: {}".format(final_directory))
    staging = final_directory + ".partial-" + uuid.uuid4().hex
    os.makedirs(staging)

    try:
        directories = (
            "geometry/vertex_buffers",
            "shaders/raw",
            "shaders/disassembly",
            "pipeline",
            "constants/raw",
            "textures/raw",
            "textures/preview",
            "outputs/color",
            "outputs/depth",
        )
        for directory in directories:
            os.makedirs(os.path.join(staging, directory), exist_ok=True)

        structured = controller.GetStructuredFile()
        action_document = {
            "schemaVersion": SCHEMA_VERSION,
            "eventId": int(action.eventId),
            "actionId": int(action.actionId),
            "name": str(action.GetName(structured)),
            "flags": flags,
            "numIndices": int(action.numIndices),
            "numInstances": int(action.numInstances),
            "baseVertex": int(action.baseVertex),
            "firstIndex": int(action.indexOffset),
            "firstVertex": int(action.vertexOffset),
            "firstInstance": int(action.instanceOffset),
            "drawIndex": int(action.drawIndex),
            "parentEventId": int(action.parent.eventId) if action.parent is not None else None,
            "childEventIds": [int(child.eventId) for child in action.children],
            "colorOutputs": [
                identifier
                for identifier in (resource_id(value) for value in action.outputs)
                if identifier is not None
            ],
            "depthOutput": resource_id(action.depthOut),
        }
        atomic_write_json(os.path.join(staging, "action.json"), action_document)

        descriptions, textures, buffers = _resource_descriptions(controller)
        usages = []
        used_resource_ids = set()
        for identifier, description in descriptions.items():
            if identifier is None:
                continue
            try:
                resource = next(
                    item
                    for item in controller.GetResources()
                    if resource_id(item.resourceId) == identifier
                )
                matching = [
                    usage
                    for usage in controller.GetUsage(resource.resourceId)
                    if int(usage.eventId) == int(event_id)
                ]
            except Exception:
                matching = []
            if not matching:
                continue
            used_resource_ids.add(identifier)
            usages.append(
                {
                    "resource": description,
                    "texture": textures.get(identifier),
                    "buffer": buffers.get(identifier),
                    "usages": [
                        {"eventId": int(item.eventId), "usage": enum_name(item.usage)}
                        for item in matching
                    ],
                }
            )
        resource_usage = {
            "schemaVersion": SCHEMA_VERSION,
            "eventId": int(event_id),
            "resources": usages,
        }
        atomic_write_json(
            os.path.join(staging, "resource-usage.json"), resource_usage
        )

        pipe = controller.GetPipelineState()
        input_mesh = {
            "stage": "input",
            "status": "not-applicable",
            "reason": "Action is not a raster Drawcall",
        }
        postvs_mesh = {
            "stage": "post-vs",
            "status": "not-applicable",
            "reason": "Action is not a raster Drawcall",
        }
        if "Drawcall" in flags:
            input_mesh = export_input_mesh(
                rd, controller, action, instance, max_resource_bytes
            )
            postvs_mesh = export_postvs_mesh(
                rd, controller, action, instance, max_resource_bytes
            )
        geometry_directory = os.path.join(staging, "geometry")
        input_mesh = _write_mesh(geometry_directory, "input", input_mesh)
        postvs_mesh = _write_mesh(geometry_directory, "post_vs", postvs_mesh)
        atomic_write_json(
            os.path.join(geometry_directory, "layout.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "input": input_mesh,
                "postVS": postvs_mesh,
            },
        )

        shaders_directory = os.path.join(staging, "shaders")
        constants_directory = os.path.join(staging, "constants")
        reflections, hashes, descriptor_records, constant_records = _shader_documents(
            rd,
            controller,
            pipe,
            action,
            shaders_directory,
            constants_directory,
            max_resource_bytes,
        )
        atomic_write_json(
            os.path.join(shaders_directory, "reflection.json"),
            {"schemaVersion": SCHEMA_VERSION, "shaders": reflections},
        )
        atomic_write_json(
            os.path.join(shaders_directory, "hashes.json"),
            {"schemaVersion": SCHEMA_VERSION, "shaders": hashes},
        )
        atomic_write_json(
            os.path.join(constants_directory, "decoded.json"),
            {"schemaVersion": SCHEMA_VERSION, "blocks": constant_records},
        )
        atomic_write_json(
            os.path.join(constants_directory, "layout.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "blocks": [
                    {
                        key: value
                        for key, value in block.items()
                        if key not in ("decoded", "raw")
                    }
                    for block in constant_records
                ],
            },
        )

        pipeline_directory = os.path.join(staging, "pipeline")
        atomic_write_json(
            os.path.join(pipeline_directory, "descriptors.json"),
            {"schemaVersion": SCHEMA_VERSION, "descriptors": descriptor_records},
        )
        render_targets = [_descriptor(item) for item in pipe.GetOutputTargets()]
        depth_target = _descriptor(pipe.GetDepthTarget())
        atomic_write_json(
            os.path.join(pipeline_directory, "render_targets.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "color": render_targets,
                "depth": depth_target,
            },
        )
        viewports = []
        scissors = []
        for index in range(16):
            try:
                viewport = _viewport(pipe.GetViewport(index))
                scissor = _scissor(pipe.GetScissor(index))
            except Exception:
                break
            if viewport is not None and (
                viewport["width"] != 0.0 or viewport["height"] != 0.0
            ):
                viewports.append(viewport)
            if scissor is not None and (
                scissor["width"] != 0 or scissor["height"] != 0
            ):
                scissors.append(scissor)
        atomic_write_json(
            os.path.join(pipeline_directory, "raster.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "primitiveTopology": enum_name(pipe.GetPrimitiveTopology()),
                "viewports": viewports,
                "scissors": scissors,
            },
        )
        d3d12 = controller.GetD3D12PipelineState()
        atomic_write_json(
            os.path.join(pipeline_directory, "depth_stencil.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "api": "D3D12" if d3d12 is not None else "generic",
                "state": str(d3d12.outputMerger.depthStencilState)
                if d3d12 is not None
                else "available in API-specific state",
            },
        )
        atomic_write_json(
            os.path.join(pipeline_directory, "blend.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "api": "D3D12" if d3d12 is not None else "generic",
                "state": str(d3d12.outputMerger.blendState)
                if d3d12 is not None
                else "available in API-specific state",
            },
        )
        root_signature, resource_states, indirect_signature = _d3d12_documents(
            controller
        )
        atomic_write_json(
            os.path.join(pipeline_directory, "root_signature.json"), root_signature
        )
        atomic_write_json(
            os.path.join(pipeline_directory, "resource_states.json"), resource_states
        )
        indirect_signature["eventId"] = int(event_id)
        indirect_signature["action"] = action_document
        atomic_write_json(
            os.path.join(pipeline_directory, "execute_indirect_signature.json"),
            indirect_signature,
        )

        texture_records = []
        texture_by_id = {
            resource_id(texture.resourceId): texture for texture in controller.GetTextures()
        }
        bound_texture_ids = set(
            record["descriptor"]["resourceId"]
            for record in descriptor_records
            if record.get("descriptor")
            and record["descriptor"].get("resourceId") in texture_by_id
        )
        bound_texture_ids.update(action_document["colorOutputs"])
        if action_document["depthOutput"]:
            bound_texture_ids.add(action_document["depthOutput"])
        for identifier in sorted(value for value in bound_texture_ids if value):
            texture = texture_by_id[identifier]
            description = textures[identifier]
            is_depth = identifier == action_document["depthOutput"] or "Depth" in description[
                "creationFlags"
            ]
            policy = texture_export_policy(
                description["format"], description["componentType"], is_depth
            )
            base = safe_name("{}_{}".format(identifier, descriptions.get(identifier, {}).get("name", "")))
            raw_name = base + policy["extension"]
            raw_path = os.path.join(staging, "textures", "raw", raw_name)
            record = {
                "resource": descriptions.get(identifier),
                "texture": description,
                "bindingEventId": int(event_id),
                "mip": 0,
                "arraySlice": 0,
                "cubeFace": 0,
                "sample": 0,
                "swizzle": "RGBA",
                "sRGB": "SRGB" in description["format"].upper(),
                "policy": policy,
                "rawPath": "raw/{}".format(raw_name),
            }
            if description["byteSize"] > max_resource_bytes:
                record["status"] = "skipped-limit"
                record["reason"] = "Texture exceeds max_resource_bytes"
            else:
                record["raw"] = _save_texture(rd, controller, texture, raw_path, policy)
                record["status"] = "exported"
                preview_name = base + ".png"
                preview_path = os.path.join(staging, "textures", "preview", preview_name)
                preview_policy = {
                    "container": "PNG",
                    "extension": ".png",
                    "fidelity": "approximation",
                }
                try:
                    record["preview"] = _save_texture(
                        rd, controller, texture, preview_path, preview_policy
                    )
                    record["previewPath"] = "preview/{}".format(preview_name)
                except Exception as exception:
                    record["previewStatus"] = "unavailable"
                    record["previewReason"] = str(exception)
            texture_records.append(record)
        atomic_write_json(
            os.path.join(staging, "textures", "bindings.json"),
            {
                "schemaVersion": SCHEMA_VERSION,
                "eventId": int(event_id),
                "textures": texture_records,
            },
        )

        output_records = {"color": [], "depth": None}
        for index, identifier in enumerate(action_document["colorOutputs"]):
            source = next(
                (
                    item
                    for item in texture_records
                    if item["texture"]["resourceId"] == identifier
                ),
                None,
            )
            if source and source.get("status") == "exported":
                source_path = os.path.join(
                    staging, "textures", source["rawPath"].replace("/", os.sep)
                )
                extension = os.path.splitext(source_path)[1]
                destination_name = "color_{}{}".format(index, extension)
                destination = os.path.join(
                    staging, "outputs", "color", destination_name
                )
                shutil.copyfile(source_path, destination)
                output_records["color"].append(
                    {
                        "resourceId": identifier,
                        "path": "color/{}".format(destination_name),
                        "sha256": sha256_file(destination),
                    }
                )
        depth_identifier = action_document["depthOutput"]
        if depth_identifier:
            source = next(
                (
                    item
                    for item in texture_records
                    if item["texture"]["resourceId"] == depth_identifier
                ),
                None,
            )
            if source and source.get("status") == "exported":
                source_path = os.path.join(
                    staging, "textures", source["rawPath"].replace("/", os.sep)
                )
                extension = os.path.splitext(source_path)[1]
                destination_name = "depth{}".format(extension)
                destination = os.path.join(
                    staging, "outputs", "depth", destination_name
                )
                shutil.copyfile(source_path, destination)
                output_records["depth"] = {
                    "resourceId": depth_identifier,
                    "path": "depth/{}".format(destination_name),
                    "sha256": sha256_file(destination),
                }
        thumbnail = next(
            (
                item
                for item in texture_records
                if item.get("previewPath")
                and item["texture"]["resourceId"]
                in action_document["colorOutputs"]
            ),
            None,
        )
        if thumbnail:
            source = os.path.join(
                staging, "textures", thumbnail["previewPath"].replace("/", os.sep)
            )
            destination = os.path.join(staging, "outputs", "thumbnail.png")
            shutil.copyfile(source, destination)
            output_records["thumbnail"] = {
                "path": "thumbnail.png",
                "sha256": sha256_file(destination),
            }
        atomic_write_json(
            os.path.join(staging, "outputs", "manifest.json"),
            {"schemaVersion": SCHEMA_VERSION, "outputs": output_records},
        )

        provenance = {
            "schemaVersion": SCHEMA_VERSION,
            "tool": "draw-evidence-package",
            "toolVersion": TOOL_VERSION,
            "renderDocVersion": str(rd.GetVersionString()),
            "captureSHA256": capture_hash,
            "captureName": os.path.basename(capture_path),
            "eventId": int(event_id),
            "api": enum_name(controller.GetAPIProperties().pipelineType),
            "source": "RenderDoc public Replay API",
            "readOnly": True,
            "captureModified": False,
            "limits": {"maxResourceBytes": int(max_resource_bytes)},
        }
        atomic_write_json(os.path.join(staging, "provenance.json"), provenance)

        artifact_records = []
        for root, _, files in os.walk(staging):
            for filename in sorted(files):
                path = os.path.join(root, filename)
                relative = os.path.relpath(path, staging).replace(os.sep, "/")
                if relative == "manifest.json":
                    continue
                artifact_records.append(
                    {
                        "path": relative,
                        "byteLength": os.path.getsize(path),
                        "sha256": sha256_file(path),
                    }
                )
        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "draw-evidence-package",
            "toolVersion": TOOL_VERSION,
            "captureSHA256": capture_hash,
            "eventId": int(event_id),
            "instance": int(instance),
            "action": action_document,
            "geometry": {
                "input": {
                    "status": input_mesh.get("status"),
                    "fidelity": input_mesh.get("fidelity"),
                    "vertexCount": input_mesh.get("vertexCount"),
                    "indexCount": input_mesh.get("indexCount"),
                },
                "postVS": {
                    "status": postvs_mesh.get("status"),
                    "fidelity": postvs_mesh.get("fidelity"),
                    "vertexCount": postvs_mesh.get("vertexCount"),
                    "indexCount": postvs_mesh.get("indexCount"),
                },
            },
            "artifacts": artifact_records,
            "durationMs": int((time.monotonic() - started) * 1000),
        }
        atomic_write_json(os.path.join(staging, "manifest.json"), manifest)
        os.makedirs(os.path.dirname(final_directory), exist_ok=True)
        os.replace(staging, final_directory)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "draw-evidence-export-result",
            "status": "succeeded",
            "captureSHA256": capture_hash,
            "eventId": int(event_id),
            "packagePath": final_directory,
            "packageName": package_name,
            "manifest": manifest,
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
