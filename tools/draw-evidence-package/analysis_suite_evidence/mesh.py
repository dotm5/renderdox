import math
import struct

from .common import enum_name, resource_id, sha256_bytes
from .glb import build_glb, validate_glb_bytes


def _contains(flags, value):
    try:
        return bool(flags & value)
    except (TypeError, ValueError):
        try:
            return (int(flags) & int(value)) != 0
        except (TypeError, ValueError):
            return False


def _unpack_format(rd, fmt, data, offset):
    if fmt.Special():
        raise ValueError("packed/special vertex format")
    width = int(fmt.compByteWidth)
    count = int(fmt.compCount)
    kind = enum_name(fmt.compType)
    chars = {
        "UInt": {1: "B", 2: "H", 4: "I", 8: "Q"},
        "SInt": {1: "b", 2: "h", 4: "i", 8: "q"},
        "Float": {2: "e", 4: "f", 8: "d"},
        "UNorm": {1: "B", 2: "H", 4: "I"},
        "UScaled": {1: "B", 2: "H", 4: "I"},
        "SNorm": {1: "b", 2: "h", 4: "i"},
        "SScaled": {1: "b", 2: "h", 4: "i"},
    }
    if kind not in chars or width not in chars[kind]:
        raise ValueError("unsupported {} x {} vertex format".format(kind, width))
    size = width * count
    if offset < 0 or offset + size > len(data):
        raise ValueError("vertex fetch extends outside available buffer bytes")
    values = struct.unpack_from("<{}{}".format(count, chars[kind][width]), data, offset)
    if kind == "UNorm":
        divisor = float((1 << (width * 8)) - 1)
        values = tuple(float(value) / divisor for value in values)
    elif kind == "SNorm":
        minimum = -(1 << (width * 8 - 1))
        divisor = float((1 << (width * 8 - 1)) - 1)
        values = tuple(
            -1.0 if value == minimum else float(value) / divisor for value in values
        )
    else:
        values = tuple(float(value) for value in values)
    if fmt.BGRAOrder() and len(values) == 4:
        values = (values[2], values[1], values[0], values[3])
    if any(not math.isfinite(value) for value in values):
        raise ValueError("vertex attribute contains a non-finite value")
    return values


def _semantic(name, used):
    upper = str(name).upper()
    if "POSITION" in upper or upper in ("POS", "IN_POS"):
        candidate = "POSITION"
    elif "NORMAL" in upper:
        candidate = "NORMAL"
    elif "TANGENT" in upper:
        candidate = "TANGENT"
    elif "COLOR" in upper or "COLOUR" in upper:
        suffix = "".join(character for character in upper if character.isdigit()) or "0"
        candidate = "COLOR_{}".format(suffix)
    elif "TEXCOORD" in upper or upper.startswith("UV"):
        suffix = "".join(character for character in upper if character.isdigit()) or "0"
        candidate = "TEXCOORD_{}".format(suffix)
    else:
        return None
    if candidate in used:
        return None
    return candidate


def _shape_attribute(semantic, value, perspective_divide=False):
    values = tuple(float(component) for component in value)
    if semantic == "POSITION":
        if perspective_divide and len(values) >= 4 and values[3] != 0.0:
            values = tuple(values[index] / values[3] for index in range(3))
        else:
            values = (values + (0.0, 0.0, 0.0))[:3]
    elif semantic == "NORMAL":
        values = (values + (0.0, 0.0, 1.0))[:3]
    elif semantic == "TANGENT":
        values = (values + (0.0, 0.0, 1.0, 1.0))[:4]
    elif semantic.startswith("TEXCOORD_"):
        values = (values + (0.0, 0.0))[:2]
    elif semantic.startswith("COLOR_"):
        values = (values + (1.0, 1.0, 1.0, 1.0))[:4]
    return values


def _topology_mode(topology):
    name = enum_name(topology)
    if "TriangleList" in name:
        return name, 4
    if "TriangleStrip" in name:
        return name, 5
    if "LineList" in name:
        return name, 1
    if "LineStrip" in name:
        return name, 3
    if "PointList" in name:
        return name, 0
    return name, None


def _read_input_indices(rd, controller, action, ib, max_resource_bytes):
    indexed = _contains(action.flags, rd.ActionFlags.Indexed)
    count = int(action.numIndices)
    if not indexed or resource_id(ib.resourceId) is None:
        return list(range(count)), None
    stride = int(ib.byteStride)
    if stride not in (1, 2, 4):
        raise ValueError("unsupported index width {}".format(stride))
    requested = count * stride
    if requested > max_resource_bytes:
        raise ValueError("index data exceeds max_resource_bytes")
    offset = int(ib.byteOffset) + int(action.indexOffset) * stride
    payload = bytes(controller.GetBufferData(ib.resourceId, offset, requested))
    if len(payload) < requested:
        raise ValueError("index buffer read returned fewer bytes than requested")
    character = {1: "B", 2: "H", 4: "I"}[stride]
    raw = list(struct.unpack_from("<{}{}".format(count, character), payload, 0))
    restart = (1 << (stride * 8)) - 1
    return [value + int(action.baseVertex) for value in raw], {
        "resourceId": resource_id(ib.resourceId),
        "byteOffset": offset,
        "byteStride": stride,
        "byteLength": len(payload),
        "sha256": sha256_bytes(payload),
        "data": payload,
        "primitiveRestartValue": restart,
        "rawIndices": raw,
    }


def _expand_strip(indices, restart):
    triangles = []
    strip = []
    for index in indices:
        if restart is not None and index == restart:
            strip = []
            continue
        strip.append(index)
        if len(strip) < 3:
            continue
        a, b, c = strip[-3:]
        if len(strip) % 2 == 0:
            a, b = b, a
        if a != b and b != c and a != c:
            triangles.extend((a, b, c))
    return triangles


def export_input_mesh(
    rd, controller, action, instance=0, max_resource_bytes=256 * 1024 * 1024
):
    pipe = controller.GetPipelineState()
    topology_name, mode = _topology_mode(pipe.GetPrimitiveTopology())
    result = {
        "stage": "input",
        "status": "unknown",
        "fidelity": "unknown",
        "coordinateSpace": "application vertex-input space",
        "topology": topology_name,
        "instance": int(instance),
        "layout": [],
        "rawVertexBuffers": [],
        "rawIndexBuffer": None,
    }
    if mode is None:
        result["reason"] = "Unsupported topology for GLB conversion"
        return result

    ib = pipe.GetIBuffer()
    source_indices, raw_index = _read_input_indices(
        rd, controller, action, ib, max_resource_bytes
    )
    if raw_index is not None:
        result["rawIndexBuffer"] = raw_index
    if mode == 5 and raw_index is not None:
        restart = raw_index["primitiveRestartValue"]
        raw = _expand_strip(raw_index["rawIndices"], restart)
        source_indices = [value + int(action.baseVertex) for value in raw]
        mode = 4
        result["topologyConversion"] = "triangle strip expanded to triangle list"

    vbs = list(pipe.GetVBuffers())
    attributes = list(pipe.GetVertexInputs())
    cache = {}
    buffer_lengths = {
        resource_id(item.resourceId): int(item.length) for item in controller.GetBuffers()
    }
    decoded = {}
    used_semantics = set()
    skipped = []

    for attribute in attributes:
        vb_index = int(attribute.vertexBuffer)
        if vb_index < 0 or vb_index >= len(vbs):
            skipped.append({"name": str(attribute.name), "reason": "vertex buffer index out of range"})
            continue
        vb = vbs[vb_index]
        identifier = resource_id(vb.resourceId)
        semantic = _semantic(attribute.name, used_semantics)
        layout = {
            "name": str(attribute.name),
            "semantic": semantic,
            "vertexBuffer": vb_index,
            "resourceId": identifier,
            "byteOffset": int(attribute.byteOffset),
            "bufferByteOffset": int(vb.byteOffset),
            "byteStride": int(vb.byteStride),
            "perInstance": bool(attribute.perInstance),
            "instanceRate": int(attribute.instanceRate),
            "format": str(attribute.format.Name()),
            "componentType": enum_name(attribute.format.compType),
            "componentByteWidth": int(attribute.format.compByteWidth),
            "componentCount": int(attribute.format.compCount),
        }
        result["layout"].append(layout)
        if semantic is None or identifier is None:
            continue
        if identifier not in cache:
            declared_length = buffer_lengths.get(identifier)
            requested_length = min(
                declared_length if declared_length is not None else max_resource_bytes,
                int(max_resource_bytes),
            )
            cache[identifier] = bytes(
                controller.GetBufferData(vb.resourceId, 0, requested_length)
            )
        values = []
        try:
            for source_index in source_indices:
                if attribute.perInstance:
                    rate = max(1, int(attribute.instanceRate))
                    fetch_index = (int(action.instanceOffset) + int(instance)) // rate
                else:
                    fetch_index = source_index
                    if not _contains(action.flags, rd.ActionFlags.Indexed):
                        fetch_index += int(action.vertexOffset)
                offset = (
                    int(vb.byteOffset)
                    + int(attribute.byteOffset)
                    + int(vb.byteStride) * fetch_index
                )
                value = _unpack_format(rd, attribute.format, cache[identifier], offset)
                values.append(_shape_attribute(semantic, value))
        except ValueError as exception:
            skipped.append({"name": str(attribute.name), "reason": str(exception)})
            continue
        decoded[semantic] = values
        used_semantics.add(semantic)

    for identifier, data in sorted(cache.items()):
        result["rawVertexBuffers"].append(
            {
                "resourceId": identifier,
                "byteOffset": 0,
                "byteLength": len(data),
                "declaredByteLength": buffer_lengths.get(identifier),
                "complete": declared_length is not None and len(data) >= declared_length,
                "sha256": sha256_bytes(data),
                "data": data,
            }
        )

    result["skippedAttributes"] = skipped
    if "POSITION" not in decoded or not source_indices:
        result["status"] = "raw-only"
        result["fidelity"] = "exact"
        result["reason"] = "No reliably decodable POSITION attribute"
        return result

    exported_indices = list(range(len(source_indices)))
    glb = build_glb(
        decoded,
        exported_indices,
        mode=mode,
        extras={
            "sourceEventId": int(action.eventId),
            "sourceIndexCount": len(source_indices),
            "instance": int(instance),
            "coordinateSpace": result["coordinateSpace"],
        },
    )
    errors = validate_glb_bytes(glb)
    if errors:
        raise ValueError("Generated input GLB failed validation: " + "; ".join(errors))
    result.update(
        {
            "status": "exported",
            "fidelity": "exact",
            "vertexCount": len(source_indices),
            "indexCount": len(exported_indices),
            "attributes": sorted(decoded),
            "glb": glb,
            "glbValidation": "pass",
        }
    )
    return result


def export_postvs_mesh(
    rd, controller, action, instance=0, max_resource_bytes=256 * 1024 * 1024
):
    result = {
        "stage": "post-vs",
        "status": "unknown",
        "fidelity": "unknown",
        "coordinateSpace": "NDC after perspective divide",
        "instance": int(instance),
        "layout": [],
        "rawVertexBuffers": [],
        "rawIndexBuffer": None,
    }
    try:
        mesh = controller.GetPostVSData(int(instance), 0, rd.MeshDataStage.VSOut)
    except Exception as exception:
        result["status"] = "unavailable"
        result["reason"] = str(exception)
        return result
    if resource_id(mesh.vertexResourceId) is None or int(mesh.numIndices) == 0:
        result["status"] = "unavailable"
        result["reason"] = "Replay returned no post-VS vertex buffer"
        return result

    reflection = controller.GetPipelineState().GetShaderReflection(rd.ShaderStage.Vertex)
    if reflection is None:
        result["status"] = "raw-only"
        result["fidelity"] = "exact"
        result["reason"] = "Vertex shader reflection is unavailable"
        return result

    count = int(mesh.numIndices)
    stride = int(mesh.vertexByteStride)
    buffer_lengths = {
        resource_id(item.resourceId): int(item.length) for item in controller.GetBuffers()
    }
    vertex_identifier = resource_id(mesh.vertexResourceId)
    declared_vertex_length = buffer_lengths.get(vertex_identifier)
    requested_vertex_length = min(
        declared_vertex_length
        if declared_vertex_length is not None
        else max_resource_bytes,
        max_resource_bytes,
    )
    vertex_data = bytes(
        controller.GetBufferData(mesh.vertexResourceId, 0, requested_vertex_length)
    )
    result["rawVertexBuffers"].append(
        {
            "resourceId": resource_id(mesh.vertexResourceId),
            "byteOffset": 0,
            "byteLength": len(vertex_data),
            "declaredByteLength": declared_vertex_length,
            "complete": declared_vertex_length is not None
            and len(vertex_data) >= declared_vertex_length,
            "sha256": sha256_bytes(vertex_data),
            "data": vertex_data,
        }
    )

    if resource_id(mesh.indexResourceId) is not None:
        index_stride = int(mesh.indexByteStride)
        offset = int(mesh.indexByteOffset)
        if count * index_stride > max_resource_bytes:
            result["status"] = "raw-only"
            result["reason"] = "Post-VS index data exceeds max_resource_bytes"
            return result
        payload = bytes(
            controller.GetBufferData(mesh.indexResourceId, offset, count * index_stride)
        )
        character = {1: "B", 2: "H", 4: "I"}.get(index_stride)
        if character is None:
            result["status"] = "raw-only"
            result["reason"] = "Unsupported post-VS index width"
            return result
        source_indices = [
            value + int(mesh.baseVertex)
            for value in struct.unpack_from(
                "<{}{}".format(count, character), payload, 0
            )
        ]
        result["rawIndexBuffer"] = {
            "resourceId": resource_id(mesh.indexResourceId),
            "byteOffset": offset,
            "byteStride": index_stride,
            "byteLength": len(payload),
            "sha256": sha256_bytes(payload),
            "data": payload,
        }
    else:
        source_indices = list(range(count))

    formats = []
    accumulated = 0
    for signature in reflection.outputSignature:
        fmt = rd.ResourceFormat()
        fmt.compByteWidth = int(rd.VarTypeByteSize(signature.varType))
        fmt.compCount = int(signature.compCount)
        fmt.compType = rd.VarTypeCompType(signature.varType)
        fmt.type = rd.ResourceFormatType.Regular
        name = str(signature.semanticIdxName or signature.varName)
        semantic = _semantic(name, set(item[0] for item in formats))
        formats.append((semantic, name, accumulated, fmt))
        accumulated += (8 if int(fmt.compByteWidth) > 4 else 4) * int(fmt.compCount)

    decoded = {}
    skipped = []
    used = set()
    for semantic, name, attribute_offset, fmt in formats:
        result["layout"].append(
            {
                "name": name,
                "semantic": semantic,
                "byteOffset": attribute_offset,
                "byteStride": stride,
                "format": str(fmt.Name()),
                "componentType": enum_name(fmt.compType),
                "componentByteWidth": int(fmt.compByteWidth),
                "componentCount": int(fmt.compCount),
            }
        )
        if semantic is None or semantic in used:
            continue
        values = []
        try:
            for source_index in source_indices:
                offset = int(mesh.vertexByteOffset) + stride * source_index + attribute_offset
                value = _unpack_format(rd, fmt, vertex_data, offset)
                values.append(
                    _shape_attribute(
                        semantic, value, perspective_divide=(semantic == "POSITION")
                    )
                )
        except ValueError as exception:
            skipped.append({"name": name, "reason": str(exception)})
            continue
        decoded[semantic] = values
        used.add(semantic)

    result["skippedAttributes"] = skipped
    if "POSITION" not in decoded:
        result["status"] = "raw-only"
        result["fidelity"] = "exact"
        result["reason"] = "No reliably decodable post-VS POSITION"
        return result

    topology_name, mode = _topology_mode(mesh.topology)
    result["topology"] = topology_name
    if mode is None:
        result["status"] = "raw-only"
        result["fidelity"] = "exact"
        result["reason"] = "Unsupported post-VS topology for GLB conversion"
        return result

    exported_indices = list(range(len(source_indices)))
    glb = build_glb(
        decoded,
        exported_indices,
        mode=mode,
        extras={
            "sourceEventId": int(action.eventId),
            "sourceIndexCount": len(source_indices),
            "instance": int(instance),
            "coordinateSpace": result["coordinateSpace"],
        },
    )
    errors = validate_glb_bytes(glb)
    if errors:
        raise ValueError("Generated post-VS GLB failed validation: " + "; ".join(errors))
    result.update(
        {
            "status": "exported",
            "fidelity": "approximation",
            "fidelityReason": "Post-VS clip positions use perspective divide for interchange",
            "vertexCount": len(source_indices),
            "indexCount": len(exported_indices),
            "attributes": sorted(decoded),
            "glb": glb,
            "glbValidation": "pass",
        }
    )
    return result
