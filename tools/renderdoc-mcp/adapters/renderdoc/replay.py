import hashlib
import json
import os
import struct
import time

from contracts import ToolError
from .convert import artifact, enum, flags, plain, rid, status_ok
from .inspect import Inspection

STAGES = ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute", "Task", "Mesh",
          "RayGen", "Intersection", "AnyHit", "ClosestHit", "Miss", "Callable")


class Replay(Inspection):
    def __init__(self, rd, directory):
        self.rd, self.directory = rd, directory
        self.capture = self.controller = None
        self.actions, self.native_actions, self.resources, self.replacements = [], {}, {}, {}
        self.event = 0

    def needs_pump(self):
        return False

    def close(self):
        if self.controller is not None:
            try:
                self.restore_replacement({})
            finally:
                self.controller.Shutdown()
                self.controller = None
        if self.capture is not None:
            self.capture.Shutdown()
            self.capture = None

    def call(self, name, args):
        if name == "open_capture":
            return self.open(args)
        if self.controller is None:
            raise ToolError("missing_session", "No capture is open")
        function = getattr(self, name, None)
        if function is None:
            raise ToolError("unsupported", "Replay operation unavailable: " + name)
        return function(args)

    def open(self, args):
        self.close()
        self.path = os.path.abspath(args["path"])
        self.capture = self.rd.OpenCaptureFile()
        started = time.monotonic()
        try:
            result = self.capture.OpenFile(self.path, "", None)
            if not status_ok(self.rd, result):
                raise ToolError("open_failed", str(result))
            result, self.controller = self.capture.OpenCapture(self.rd.ReplayOptions(), None)
            if not status_ok(self.rd, result) or self.controller is None:
                raise ToolError("replay_failed", str(result))
            self.actions, self.native_actions, self.resources = [], {}, {}
            self.inspection_cache = {}
            self.structured = self.controller.GetStructuredFile()
            def visit(items, ancestry):
                for action in items:
                    name = str(action.GetName(self.structured))
                    event = int(action.eventId)
                    info = {"eventId": event, "name": name, "flags": flags(action.flags, self.rd.ActionFlags),
                            "numIndices": int(action.numIndices), "numInstances": int(action.numInstances),
                            "indexOffset": int(action.indexOffset), "vertexOffset": int(action.vertexOffset),
                            "instanceOffset": int(action.instanceOffset), "baseVertex": int(action.baseVertex),
                            "dispatchDimension": plain(action.dispatchDimension), "ancestry": ancestry,
                            "leaf": not bool(action.children), "outputs": [rid(x) for x in action.outputs],
                            "depthOutput": rid(action.depthOut)}
                    self.actions.append(info)
                    self.native_actions[event] = action
                    visit(action.children, ancestry + [{"eventId": event, "name": name}])
            visit(self.controller.GetRootActions(), [])
            descriptions = self.controller.GetResources()
            names = {rid(x.resourceId): str(x.name) for x in descriptions}
            for kind, values in (("texture", self.controller.GetTextures()), ("buffer", self.controller.GetBuffers())):
                for item in values:
                    identifier = rid(item.resourceId)
                    self.resources[identifier] = (kind, item, names.get(identifier, ""))
            for item in descriptions:
                key = rid(item.resourceId)
                if key and key not in self.resources:
                    kind = enum(item.type, getattr(self.rd, "ResourceType", None)).lower()
                    self.resources[key] = (kind, item, str(item.name))
            return dict(self.get_capture_summary({}), openDurationMs=(time.monotonic() - started) * 1000)
        except Exception:
            self.close()
            raise

    def set_event(self, event):
        event = int(event)
        if event not in self.native_actions:
            raise ToolError("missing_event", "No action at EID " + str(event))
        self.controller.SetFrameEvent(event, True)
        self.event = event
        return self.controller.GetPipelineState()

    def stage(self, name):
        if name not in STAGES or not hasattr(self.rd.ShaderStage, name):
            raise ToolError("unsupported_stage", name)
        return getattr(self.rd.ShaderStage, name)

    def resource(self, identifier, kind=None):
        item = self.resources.get(identifier)
        if item is None or (kind and item[0] != kind):
            raise ToolError("missing_resource", str(identifier))
        return item[1]

    def subresource(self, args):
        sub = self.rd.Subresource()
        sub.mip, sub.slice, sub.sample = args.get("mip", 0), args.get("slice", 0), args.get("sample", 0)
        return sub

    def get_capabilities(self, args):
        props = plain(self.controller.GetAPIProperties())
        return {"apiProperties": props, "stages": [s for s in STAGES if hasattr(self.rd.ShaderStage, s)],
                "targetShaderEncodings": [enum(x, self.rd.ShaderEncoding) for x in self.controller.GetTargetShaderEncodings()],
                "pixelHistory": {"available": bool(getattr(self.controller.GetAPIProperties(), "pixelHistory", False))},
                "shaderDebugging": {"available": bool(getattr(self.controller.GetAPIProperties(), "shaderDebugging", False)),
                                    "scope": "Actual stage/encoding support is checked on invocation"},
                "actionVisibility": hasattr(self.controller, "SetDisabledActions"),
                "methods": sorted(x for x in dir(self.controller) if not x.startswith("_") and callable(getattr(self.controller, x)))}

    def get_capture_summary(self, args):
        frame = self.controller.GetFrameInfo()
        result = {"path": self.path, "api": enum(self.controller.GetAPIProperties().pipelineType, self.rd.GraphicsAPI),
                  "frame": {x: plain(getattr(frame, x)) for x in ("frameNumber", "captureTime", "compressedFileSize", "uncompressedFileSize", "persistentSize", "initDataSize") if hasattr(frame, x)}, "actionCount": len(self.actions),
                  "textureCount": sum(x[0] == "texture" for x in self.resources.values()),
                  "bufferCount": sum(x[0] == "buffer" for x in self.resources.values()),
                  "capabilities": self.get_capabilities({})}
        thumbnail = self.capture.GetThumbnail(self.rd.FileType.PNG, 512)
        if thumbnail.data:
            result["thumbnail"] = artifact(self.directory, bytes(thumbnail.data), "png", mimeType="image/png")
        return result

    def find_actions(self, args):
        query, flags = args.get("query", "").lower(), args.get("flags", "").lower()
        values = [x for x in self.actions if query in (x["name"] + str(x["ancestry"])).lower()
                  and flags in x["flags"].lower() and args.get("minEventId", 0) <= x["eventId"] <= args.get("maxEventId", 2**32 - 1)]
        offset, limit = args.get("offset", 0), args.get("limit", 200)
        return {"total": len(values), "actions": values[offset:offset + limit], "nextOffset": offset + limit if offset + limit < len(values) else None}

    def get_action(self, args):
        event = args["eventId"]
        for action in self.actions:
            if action["eventId"] == event:
                return action
        raise ToolError("missing_event", str(event))

    def description(self, identifier):
        kind, item, name = self.resources[identifier]
        result = {"resourceId": identifier, "name": name, "kind": kind, "description": plain(item)}
        if kind == "texture":
            result["description"]["formatName"] = item.format.Name()
            result["description"]["format"].update(type=enum(item.format.type, self.rd.ResourceFormatType), compType=enum(item.format.compType, self.rd.CompType),
                                                   bgraOrder=item.format.BGRAOrder(), srgbCorrected=item.format.SRGBCorrected())
        return result

    def list_resources(self, args):
        query = args.get("query", "").lower()
        values = [self.description(k) for k, (kind, item, name) in self.resources.items()
                  if (not args.get("kind") or args["kind"] == kind) and query in (k + name).lower()]
        offset, limit = args.get("offset", 0), args.get("limit", 200)
        return {"total": len(values), "resources": values[offset:offset + limit], "nextOffset": offset + limit if offset + limit < len(values) else None}

    def pipeline(self, pipe):
        stages = []
        for name in STAGES:
            if not hasattr(self.rd.ShaderStage, name):
                continue
            stage = self.stage(name)
            shader = rid(pipe.GetShader(stage))
            if not shader:
                continue
            bindings = {}
            for label, method in (("constantBlocks", "GetConstantBlocks"), ("readOnly", "GetReadOnlyResources"),
                                  ("readWrite", "GetReadWriteResources"), ("samplers", "GetSamplers")):
                function = getattr(pipe, method, None)
                bindings[label] = plain(function(stage, False)) if function else {"unavailable": method}
            reflection = pipe.GetShaderReflection(stage)
            stages.append({"stage": name, "resourceId": shader, "entryPoint": pipe.GetShaderEntryPoint(stage),
                           "encoding": enum(reflection.encoding, self.rd.ShaderEncoding) if reflection else None, "bindings": bindings})
        common = {"eventId": self.event, "api": enum(self.controller.GetAPIProperties().pipelineType, self.rd.GraphicsAPI),
                  "shaders": stages, "topology": enum(pipe.GetPrimitiveTopology(), self.rd.Topology),
                  "outputTargets": plain(pipe.GetOutputTargets()), "depthTarget": plain(pipe.GetDepthTarget()),
                  "vertexBuffers": plain(pipe.GetVBuffers()), "indexBuffer": plain(pipe.GetIBuffer()),
                  "vertexInputs": plain(pipe.GetVertexInputs())}
        for label, method in (("depthTest", "GetDepthTestState"), ("colorBlend", "GetColorBlends"),
                              ("viewports", "GetViewports"), ("scissors", "GetScissors")):
            function = getattr(pipe, method, None)
            common[label] = plain(function()) if function else {"unavailable": method}
        api = common["api"]
        function = getattr(self.controller, "Get" + ("GL" if api == "OpenGL" else "Vulkan" if api == "Vulkan" else api) + "PipelineState", None)
        if function:
            common["apiState"] = plain(function())
        return common

    def get_pipeline_state(self, args):
        return self.pipeline(self.set_event(args["eventId"]))

    def shader_pipeline(self, pipe, stage):
        return pipe.GetComputePipelineObject() if stage == self.rd.ShaderStage.Compute else pipe.GetGraphicsPipelineObject()

    def get_shader(self, args):
        pipe = self.set_event(args["eventId"])
        stage = self.stage(args["stage"])
        ref = pipe.GetShaderReflection(stage)
        if ref is None:
            raise ToolError("missing_shader", args["stage"])
        reflection = plain(ref)
        raw = bytes(ref.rawBytes)
        result = {"eventId": self.event, "stage": args["stage"], "resourceId": rid(pipe.GetShader(stage)),
                  "entryPoint": str(pipe.GetShaderEntryPoint(stage)), "reflection": reflection,
                  "bytecodeSHA256": hashlib.sha256(raw).hexdigest()}
        if args.get("includeBytecode", True):
            result["bytecode"] = artifact(self.directory, raw, "bin", encoding=enum(ref.encoding, self.rd.ShaderEncoding))
        if args.get("includeDisassembly", True):
            text = str(self.controller.DisassembleShader(self.shader_pipeline(pipe, stage), ref, ""))
            lines = text.splitlines()
            filtered = [(i, line) for i, line in enumerate(lines) if args.get("search", "").lower() in line.lower()]
            offset, count = args.get("lineOffset", 0), args.get("lineCount", 200)
            result.update({"disassembly": artifact(self.directory, text, "txt", mimeType="text/plain"),
                           "lines": [{"line": i, "text": x} for i, x in filtered[offset:offset + count]],
                           "totalLines": len(lines), "matchingLines": len(filtered)})
        return result

    def get_constants(self, args):
        pipe = self.set_event(args["eventId"])
        stage = self.stage(args["stage"])
        ref = pipe.GetShaderReflection(stage)
        if ref is None:
            raise ToolError("missing_shader", args["stage"])
        indices = [args["blockIndex"]] if "blockIndex" in args else range(len(ref.constantBlocks))
        blocks = []
        for index in indices:
            if index >= len(ref.constantBlocks):
                raise ToolError("missing_constant_block", str(index))
            binding = pipe.GetConstantBlock(stage, index, args.get("arrayIndex", 0))
            descriptor = binding.descriptor
            block = ref.constantBlocks[index]
            values = self.controller.GetCBufferVariableContents(self.shader_pipeline(pipe, stage), pipe.GetShader(stage), stage,
                      pipe.GetShaderEntryPoint(stage), index, descriptor.resource, descriptor.byteOffset, descriptor.byteSize)
            layouts = {str(x.name): x for x in block.variables}
            item = {"index": index, "name": str(block.name), "variables": [self.variable(x, layouts.get(str(x.name))) for x in values]}
            if not args.get("compact"):
                item.update(binding=plain(binding), layout=plain(block))
            if args.get("includeRaw", False) and rid(descriptor.resource):
                length = int(descriptor.byteSize) or int(block.byteSize)
                raw = bytes(self.controller.GetBufferData(descriptor.resource, descriptor.byteOffset, length))
                item["raw"] = artifact(self.directory, raw, "bin", byteOffset=int(descriptor.byteOffset))
            blocks.append(item)
        return {"eventId": self.event, "stage": args["stage"], "blocks": blocks}

    def variable(self, value, layout=None, base_offset=0):
        name = enum(value.type, self.rd.VarType)
        fields = {"Float": "f32v", "Double": "f64v", "Half": "f16v", "SInt": "s32v", "UInt": "u32v",
                  "SShort": "s16v", "UShort": "u16v", "SLong": "s64v", "ULong": "u64v", "SByte": "s8v",
                  "UByte": "u8v", "Bool": "u32v", "Enum": "u32v", "GPUPointer": "u64v"}
        offset = base_offset + int(layout.byteOffset) if layout else None
        result = {"name": str(value.name), "type": name, "rows": int(value.rows), "columns": int(value.columns),
                  "flags": int(value.flags), "byteOffset": offset}
        if value.members:
            members = {str(x.name): x for x in layout.type.members} if layout else {}
            stride = int(layout.type.arrayByteStride) if layout and layout.type.elements else 0
            result["members"] = [self.variable(x, members.get(str(x.name)), (offset or base_offset) + i * stride)
                                 for i, x in enumerate(value.members)]
        elif name in fields:
            data = list(getattr(value.value, fields[name]))[:int(value.rows) * int(value.columns)]
            if name == "Half":
                data = [struct.unpack("<e", struct.pack("<H", x))[0] for x in data]
            result["values"] = plain(data)
        else:
            result["rawValue"] = plain(value.value)
            result["interpretation"] = "Unknown/resource type; raw union views retained"
        return result

    def get_buffer_data(self, args):
        self.set_event(args["eventId"])
        buffer = self.resource(args["resourceId"], "buffer")
        offset = args.get("offset", 0)
        length = args.get("length", int(buffer.length) - offset)
        if offset > buffer.length or length > buffer.length - offset:
            raise ToolError("invalid_range", "Buffer range exceeds the resource")
        data = bytes(self.controller.GetBufferData(buffer.resourceId, offset, length)) if length else b""
        result = {"resourceId": args["resourceId"], "offset": offset, "data": artifact(self.directory, data)}
        if args.get("decode"):
            formats = {"f32": "f", "u32": "I", "i32": "i", "u16": "H", "u8": "B"}
            fmt = formats.get(args["decode"])
            if not fmt:
                raise ToolError("unsupported_decode", args["decode"])
            size = struct.calcsize(fmt)
            result["values"] = plain([x[0] for x in struct.iter_unpack("<" + fmt, data[:len(data) // size * size])])
            result["trailingBytes"] = len(data) % size
        return result

    def texture_data(self, args):
        texture = self.resource(args["resourceId"], "texture")
        sub = self.subresource(args)
        if sub.mip >= texture.mips or sub.slice >= texture.arraysize or sub.sample >= texture.msSamp:
            raise ToolError("invalid_subresource", "mip/slice/sample outside the texture")
        data = bytes(self.controller.GetTextureData(texture.resourceId, sub))
        return {"resourceId": args["resourceId"], "eventId": self.event, "subresource": plain(sub),
                "texture": self.description(args["resourceId"])["description"],
                "data": artifact(self.directory, data, "bin", mimeType="application/octet-stream"),
                "interpretation": "native untransformed subresource; 3D contains the whole mip"}

    def read_texture(self, args):
        self.set_event(args["eventId"])
        return self.texture_data(args)

    def texture_preview(self, args):
        texture = self.resource(args["resourceId"], "texture")
        save = self.rd.TextureSave()
        save.resourceId = texture.resourceId
        file_type = args.get("fileType", "PNG").upper()
        if file_type not in ("PNG", "EXR", "DDS"):
            raise ToolError("unsupported_format", file_type)
        save.destType = getattr(self.rd.FileType, file_type)
        save.mip = args.get("mip", 0)
        save.slice.sliceIndex, save.sample.sampleIndex = args.get("slice", 0), args.get("sample", 0)
        save.comp.blackPoint, save.comp.whitePoint = args.get("blackPoint", 0.0), args.get("whitePoint", 1.0)
        result = artifact(self.directory, b"", file_type.lower(), mimeType="image/png" if file_type == "PNG" else "application/octet-stream")
        status = self.controller.SaveTexture(save, result["path"])
        if not status_ok(self.rd, status):
            raise ToolError("save_texture_failed", str(status))
        with open(result["path"], "rb") as stream:
            data = stream.read()
        result.update(byteLength=len(data), sha256=hashlib.sha256(data).hexdigest())
        return {"resourceId": args["resourceId"], "eventId": self.event, "image": result,
                "texture": self.description(args["resourceId"])["description"], "subresource": plain(self.subresource(args)),
                "displayTransform": {"fileType": file_type, "blackPoint": save.comp.blackPoint, "whitePoint": save.comp.whitePoint,
                                     "previewOnly": file_type == "PNG", "mapping": "RenderDoc TextureSave format conversion"}}

    def view_texture(self, args):
        self.set_event(args["eventId"])
        return self.texture_preview(args)

    def sample_pixels(self, args):
        self.set_event(args["eventId"])
        tex = self.resource(args["resourceId"], "texture")
        cast = getattr(self.rd.CompType, args.get("typeCast", "Typeless"))
        return {"resourceId": args["resourceId"], "subresource": plain(self.subresource(args)),
                "pixels": [{"x": x, "y": y, "value": plain(self.controller.PickPixel(tex.resourceId, x, y, self.subresource(args), cast))}
                           for x, y in args["points"]]}

    def get_mesh(self, args):
        pipe = self.set_event(args["eventId"])
        result = {"eventId": self.event, "vertexInputs": plain(pipe.GetVertexInputs()),
                  "vertexBuffers": plain(pipe.GetVBuffers()), "indexBuffer": plain(pipe.GetIBuffer()),
                  "action": self.get_action(args)}
        if args.get("includeData", False):
            for buffer in list(pipe.GetVBuffers()) + [pipe.GetIBuffer()]:
                identifier = rid(buffer.resourceId)
                if identifier:
                    data = bytes(self.controller.GetBufferData(buffer.resourceId, 0, 0))
                    result.setdefault("buffers", []).append({"resourceId": identifier, "data": artifact(self.directory, data)})
        return result

    def get_post_vs_data(self, args):
        self.set_event(args["eventId"])
        stage = getattr(self.rd.MeshDataStage, args.get("stage", "VSOut"))
        mesh = self.controller.GetPostVSData(args.get("instance", 0), args.get("view", 0), stage)
        result = {"eventId": self.event, "mesh": plain(mesh)}
        if args.get("includeData", True):
            for label, resource, offset, length in (("vertices", mesh.vertexResourceId, 0, 0),
                    ("indices", mesh.indexResourceId, mesh.indexByteOffset, mesh.indexByteStride * mesh.numIndices)):
                if rid(resource):
                    data = bytes(self.controller.GetBufferData(resource, offset, length))
                    result[label] = artifact(self.directory, data)
        return result

    def get_resource_usage(self, args):
        resource = self.resource(args["resourceId"])
        return {"resourceId": args["resourceId"], "usage": plain(self.controller.GetUsage(resource.resourceId))}

    def trace_resource_flow(self, args):
        result = self.get_resource_usage(args)
        lookup = {x["eventId"]: x for x in self.actions}
        for usage in result["usage"]:
            usage["action"] = lookup.get(usage["eventId"])
        return result

    def pixel_history(self, args):
        self.set_event(args["eventId"])
        if not getattr(self.controller.GetAPIProperties(), "pixelHistory", False):
            raise ToolError("unsupported", "PixelHistory unavailable for this backend")
        texture = self.resource(args["resourceId"], "texture")
        values = self.controller.PixelHistory(texture.resourceId, args["x"], args["y"], self.subresource(args),
                                              getattr(self.rd.CompType, args.get("typeCast", "Typeless")))
        return {"eventId": self.event, "resourceId": args["resourceId"], "modifications": plain(values)}

    def debug_shader(self, args):
        self.set_event(args["eventId"])
        trace = None
        try:
            stage = args["stage"]
            if stage == "Pixel":
                inputs = self.rd.DebugPixelInputs()
                if "sample" in args:
                    inputs.sample = args["sample"]
                if "primitive" in args:
                    inputs.primitive = args["primitive"]
                trace = self.controller.DebugPixel(args["x"], args["y"], inputs)
            elif stage == "Vertex":
                trace = self.controller.DebugVertex(args.get("vertex", 0), args.get("instance", 0), args.get("index", 0), args.get("view", 0))
            elif stage == "Compute":
                trace = self.controller.DebugThread(args.get("group", [0, 0, 0]), args.get("thread", [0, 0, 0]))
            else:
                raise ToolError("unsupported_stage", "Debugging supports Pixel/Vertex/Compute here")
            if trace is None or trace.debugger is None:
                raise ToolError("unsupported", "No debugger returned for the selected shader/fragment")
            steps = []
            while True:
                batch = self.controller.ContinueDebug(trace.debugger)
                if not batch:
                    break
                for state in batch:
                    item = {"stepIndex": int(state.stepIndex), "nextInstruction": int(state.nextInstruction),
                            "callstack": plain(state.callstack), "flags": flags(state.flags, self.rd.ShaderEvents)}
                    item["changes"] = [{"before": self.variable(change.before), "after": self.variable(change.after)} for change in state.changes]
                    steps.append(item)
            payload = {"trace": plain(trace), "steps": steps}
            return {"eventId": self.event, "stage": stage, "stepCount": len(steps),
                    "trace": artifact(self.directory, json.dumps(payload), "json", mimeType="application/json")}
        finally:
            if trace is not None:
                self.controller.FreeTrace(trace)

    def replace_shader(self, args):
        pipe = self.set_event(args["eventId"])
        stage = self.stage(args["stage"])
        original = pipe.GetShader(stage)
        if not rid(original):
            raise ToolError("missing_shader", args["stage"])
        encoding = getattr(self.rd.ShaderEncoding, args["encoding"])
        if "sourceFile" in args:
            with open(args["sourceFile"], "rb") as stream:
                source = stream.read()
        elif "source" in args:
            source = args["source"].encode("utf-8")
        else:
            raise ToolError("invalid_arguments", "source or sourceFile required")
        flags = self.rd.ShaderCompileFlags()
        for flag in args.get("compileFlags", []):
            pair = self.rd.ShaderCompileFlag()
            pair.name, pair.value = flag["name"], flag["value"]
            flags.flags.append(pair)
        replacement, diagnostics = self.controller.BuildTargetShader(args.get("entryPoint", pipe.GetShaderEntryPoint(stage)),
                                                                      encoding, source, flags, stage)
        if not rid(replacement):
            return {"installed": False, "diagnostics": str(diagnostics)}
        key = rid(original)
        if key in self.replacements:
            self.restore_replacement({"resourceId": key})
        try:
            self.controller.ReplaceResource(original, replacement)
            self.inspection_cache = {}
            self.replacements[key] = (original, replacement)
            self.controller.SetFrameEvent(self.event, True)
        except Exception:
            self.controller.RemoveReplacement(original)
            self.controller.FreeTargetResource(replacement)
            raise
        return {"installed": True, "resourceId": key, "replacement": rid(replacement), "diagnostics": str(diagnostics)}

    def restore_replacement(self, args):
        if self.replacements:
            self.inspection_cache = {}
        for key in list(self.replacements):
            if args.get("resourceId") and key != args["resourceId"]:
                continue
            original, replacement = self.replacements.pop(key)
            self.controller.RemoveReplacement(original)
            self.controller.FreeTargetResource(replacement)
        if self.event and self.controller:
            self.controller.SetFrameEvent(self.event, True)
        return {"remaining": list(self.replacements)}

    def get_draw_evidence(self, args):
        pipe = self.set_event(args["eventId"])
        result = {"action": self.get_action(args), "pipeline": self.pipeline(pipe), "mesh": self.get_mesh(args)}
        if args.get("includeConstants", True):
            result["constants"] = [self.get_constants(dict(args, stage=x["stage"])) for x in result["pipeline"]["shaders"]]
        if args.get("includePreviews", True):
            result["previews"] = []
            for output in pipe.GetOutputTargets():
                identifier = rid(output.resource)
                if identifier:
                    result["previews"].append(self.texture_preview(dict(args, resourceId=identifier, mip=int(output.firstMip), slice=int(output.firstSlice))))
        return result

    def diff_event(self, args):
        event = args["eventId"]
        pipe = self.set_event(event)
        action = self.native_actions[event]
        if action.children:
            raise ToolError("ambiguous_event", "Select a leaf action for event diff")
        identifiers = args.get("resourceIds")
        if identifiers is None:
            identifiers = [rid(x.resource) for x in pipe.GetOutputTargets() if rid(x.resource)]
            if rid(pipe.GetDepthTarget().resource):
                identifiers.append(rid(pipe.GetDepthTarget().resource))
        if not identifiers:
            raise ToolError("missing_outputs", "Specify resourceIds for a dispatch/UAV operation")
        after = [self.texture_data(dict(args, resourceId=x)) for x in identifiers]
        previews_after = [self.texture_preview(dict(args, resourceId=x)) for x in identifiers] if args.get("displayImages", True) else []
        method, previous = "previous_api_event", None
        disabled = False
        try:
            if hasattr(self.controller, "SetDisabledActions"):
                accepted = self.controller.SetDisabledActions([event])
                disabled = event in accepted
            if disabled:
                self.controller.SetFrameEvent(event, True)
                method = "same_event_with_action_omitted"
            else:
                candidates = sorted(set(int(api.eventId) for a in self.native_actions.values() for api in a.events if int(api.eventId) < event))
                if not candidates:
                    raise ToolError("unavailable_pre_state", "No preceding API event exposed for this action")
                previous = candidates[-1]
                self.controller.SetFrameEvent(previous, True)
            before = [self.texture_data(dict(args, resourceId=x)) for x in identifiers]
            previews_before = [self.texture_preview(dict(args, resourceId=x)) for x in identifiers] if args.get("displayImages", True) else []
            return {"eventId": event, "preStateMethod": method, "previousApiEvent": previous,
                    "before": before, "after": after, "previewsBefore": previews_before, "previewsAfter": previews_after,
                    "scope": "Specified texture mip/slice/sample; no pixel changes do not prove no object was drawn"}
        finally:
            if hasattr(self.controller, "SetDisabledActions"):
                self.controller.SetDisabledActions([])
            self.controller.SetFrameEvent(event, True)

    def build_signatures(self, args):
        shader_cache, texture_cache, signatures = {}, {}, []
        for action in self.actions:
            if not action["leaf"] or not (self.native_actions[action["eventId"]].flags & (self.rd.ActionFlags.Drawcall | self.rd.ActionFlags.Dispatch)):
                continue
            pipe = self.set_event(action["eventId"])
            shaders = {}
            for name in STAGES:
                if not hasattr(self.rd.ShaderStage, name):
                    continue
                stage = self.stage(name)
                key = rid(pipe.GetShader(stage))
                if key:
                    if key not in shader_cache:
                        ref = pipe.GetShaderReflection(stage)
                        shader_cache[key] = hashlib.sha256(bytes(ref.rawBytes)).hexdigest() if ref else None
                    shaders[name] = shader_cache[key]
            outputs = []
            for descriptor in list(pipe.GetOutputTargets()) + [pipe.GetDepthTarget()]:
                key = rid(descriptor.resource)
                if key and key in self.resources:
                    texture = self.resources[key][1]
                    outputs.append([int(texture.width), int(texture.height), str(texture.format.Name())])
            inputs = []
            if args.get("includeTextureHashes", False):
                for name in STAGES:
                    if not hasattr(self.rd.ShaderStage, name):
                        continue
                    for binding in pipe.GetReadOnlyResources(self.stage(name), True):
                        key = rid(binding.descriptor.resource)
                        if key and key in self.resources and self.resources[key][0] == "texture":
                            if key not in texture_cache:
                                texture_cache[key] = hashlib.sha256(bytes(self.controller.GetTextureData(self.resources[key][1].resourceId, self.rd.Subresource()))).hexdigest()
                            inputs.append(texture_cache[key])
            mesh = pipe.GetIBuffer()
            index_hash = None
            if rid(mesh.resourceId):
                stride = int(mesh.byteStride)
                raw = bytes(self.controller.GetBufferData(mesh.resourceId, int(mesh.byteOffset) + action["indexOffset"] * stride, action["numIndices"] * stride))
                index_hash = hashlib.sha256(raw).hexdigest()
            signatures.append(dict(action, shaders=shaders, outputDescriptions=outputs,
                                   topology=enum(pipe.GetPrimitiveTopology(), self.rd.Topology), indexHash=index_hash, textureHashes=sorted(set(inputs))))
        return {"algorithmVersion": 1, "signatures": signatures}
