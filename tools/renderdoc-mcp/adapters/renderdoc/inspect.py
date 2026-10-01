"""Public-API analysis helpers. Compatible with the packaged Python 3.6 worker."""
import hashlib
import json
import math
import struct

from contracts import ToolError
from .convert import enum, flags, plain, rid


class Inspection:
    def locate_draws_at_pixel(self, args):
        texture = self.resource(args["resourceId"], "texture")
        width, height = max(1, texture.width >> args.get("mip", 0)), max(1, texture.height >> args.get("mip", 0))
        if args["x"] >= width or args["y"] >= height:
            raise ToolError("invalid_pixel", "Coordinates outside the chosen mip")
        history = self.pixel_history(args)
        by_event = {}
        failure_fields = ("backfaceCulled", "depthClipped", "scissorClipped", "shaderDiscarded",
                          "depthTestFailed", "stencilTestFailed", "sampleMasked", "predicationSkipped", "unboundPS")
        for modification in history["modifications"]:
            event = int(modification["eventId"])
            if event > args["eventId"]:
                continue
            record = by_event.setdefault(event, {"eventId": event, "action": next((x for x in self.actions if x["eventId"] == event), None),
                                                "fragments": [], "failureReasons": []})
            reasons = [x for x in failure_fields if modification.get(x)]
            record["fragments"].append(dict(modification, failureReasons=reasons))
            record["failureReasons"] = sorted(set(record["failureReasons"] + reasons))
        candidates = sorted(by_event.values(), key=lambda x: x["eventId"], reverse=True)
        for candidate in candidates[:args.get("limit", 20)]:
            if candidate["action"]:
                pipe = self.set_event(candidate["eventId"])
                candidate["pipeline"] = self.compact_pipeline(pipe)
                candidate["passedFragments"] = sum(not x["failureReasons"] for x in candidate["fragments"])
                if args.get("includePreviews", False):
                    candidate["preview"] = self.texture_preview(dict(args, eventId=candidate["eventId"]))
        self.set_event(args["eventId"])
        return {"eventId": args["eventId"], "resourceId": args["resourceId"], "x": args["x"], "y": args["y"],
                "total": len(candidates), "candidates": candidates[:args.get("limit", 20)],
                "interpretation": "Writes to this resource/pixel only. Final compositing may hide earlier scene draws; use the dependency graph to find intermediate outputs."}

    def compact_pipeline(self, pipe):
        stages = ("Vertex", "Hull", "Domain", "Geometry", "Pixel", "Compute", "Task", "Mesh")
        shaders, bindings = {}, []
        for name in stages:
            if not hasattr(self.rd.ShaderStage, name):
                continue
            stage = self.stage(name)
            shader = rid(pipe.GetShader(stage))
            if not shader:
                continue
            ref = pipe.GetShaderReflection(stage)
            shaders[name] = {"resourceId": shader, "sha256": hashlib.sha256(bytes(ref.rawBytes)).hexdigest() if ref else None,
                             "entryPoint": str(pipe.GetShaderEntryPoint(stage))}
            for role, method in (("constant", "GetConstantBlocks"), ("read", "GetReadOnlyResources"), ("readWrite", "GetReadWriteResources")):
                for index, bound in enumerate(getattr(pipe, method)(stage, True)):
                    desc = bound.descriptor
                    resource = rid(desc.resource)
                    if resource:
                        bindings.append({"stage": name, "role": role, "slot": index, "resourceId": resource,
                                         "access": plain(bound.access), "byteOffset": int(desc.byteOffset), "byteSize": int(desc.byteSize),
                                         "firstMip": int(desc.firstMip), "firstSlice": int(desc.firstSlice)})
        result = {"shaders": shaders, "bindings": bindings, "topology": enum(pipe.GetPrimitiveTopology(), self.rd.Topology),
                "outputs": plain(pipe.GetOutputTargets()), "depth": plain(pipe.GetDepthTarget()),
                "vertexBuffers": plain(pipe.GetVBuffers()), "indexBuffer": plain(pipe.GetIBuffer()),
                "vertexInputs": plain(pipe.GetVertexInputs())}
        for label, method in (("depthTest", "GetDepthTestState"), ("colorBlend", "GetColorBlends"), ("viewports", "GetViewports"), ("scissors", "GetScissors")):
            function = getattr(pipe, method, None)
            result[label] = plain(function()) if function else {"unavailable": method}
        return result

    def analysis_snapshot(self, args):
        cache_key = (args.get("minEventId", 0), args.get("maxEventId", 2**32-1), bool(args.get("includeConstants")), bool(args.get("includeGeometryHashes")))
        cache = getattr(self, "inspection_cache", {})
        if cache_key in cache:
            return cache[cache_key]
        snapshots = []
        for action in self.actions:
            if not action["leaf"] or not args.get("minEventId", 0) <= action["eventId"] <= args.get("maxEventId", 2**32 - 1):
                continue
            native = self.native_actions[action["eventId"]]
            if not native.flags & (self.rd.ActionFlags.Drawcall | self.rd.ActionFlags.Dispatch):
                continue
            pipe = self.set_event(action["eventId"])
            state = self.compact_pipeline(pipe)
            mesh = pipe.GetIBuffer()
            index_hash, vertex_hashes = None, []
            if rid(mesh.resourceId) and mesh.byteStride and action["numIndices"]:
                raw = bytes(self.controller.GetBufferData(mesh.resourceId, int(mesh.byteOffset) + action["indexOffset"] * int(mesh.byteStride), action["numIndices"] * int(mesh.byteStride)))
                index_hash = hashlib.sha256(raw).hexdigest()
                if args.get("includeGeometryHashes") and int(mesh.byteStride) in (2, 4) and raw:
                    fmt = "H" if mesh.byteStride == 2 else "I"
                    indices = [x[0] for x in struct.iter_unpack("<" + fmt, raw)]
                    restart = (1 << (mesh.byteStride * 8)) - 1
                    indices = [x + action["baseVertex"] for x in indices if x != restart]
                    if indices and min(indices) >= 0:
                        for buffer in pipe.GetVBuffers():
                            if not rid(buffer.resourceId) or not buffer.byteStride:
                                continue
                            offset = int(buffer.byteOffset) + min(indices) * int(buffer.byteStride)
                            length = (max(indices) - min(indices) + 1) * int(buffer.byteStride)
                            source = self.resources.get(rid(buffer.resourceId))
                            if source and offset + length <= source[1].length:
                                vertex_hashes.append(hashlib.sha256(bytes(self.controller.GetBufferData(buffer.resourceId, offset, length))).hexdigest())
            record = dict(action, state=state, indexHash=index_hash, vertexHashes=vertex_hashes)
            if args.get("includeConstants"):
                record["constants"] = [self.get_constants({"eventId": action["eventId"], "stage": stage, "compact": True}) for stage in state["shaders"]]
            snapshots.append(record)
        result = {"events": snapshots}
        cache[cache_key] = result
        self.inspection_cache = cache
        return result

    def resource_fingerprints(self, args):
        snapshot = self.analysis_snapshot({})["events"]
        roles = {}
        for event in snapshot:
            hashes = {k: v["sha256"] for k, v in event["state"]["shaders"].items()}
            for binding in event["state"]["bindings"]:
                signature = [binding["stage"], binding["role"], binding["slot"], hashes.get(binding["stage"])]
                roles.setdefault(binding["resourceId"], set()).add(json.dumps(signature))
            for slot, output in enumerate(event["state"]["outputs"] + [event["state"]["depth"]]):
                if output.get("resource"):
                    roles.setdefault(output["resource"], set()).add(json.dumps(["output", slot, sorted(hashes.items())]))
            for slot, buffer in enumerate(event["state"]["vertexBuffers"] + [event["state"]["indexBuffer"]]):
                if buffer.get("resourceId"):
                    roles.setdefault(buffer["resourceId"], set()).add(json.dumps(["geometry", slot, buffer.get("byteStride")]))
        self.set_event(args["eventId"])
        values = []
        for key, (kind, item, name) in self.resources.items():
            if kind not in ("texture", "buffer", "shader") or (args.get("kind") and kind != args["kind"]):
                continue
            desc = self.description(key)
            signature = {"kind": kind}
            if kind == "texture":
                signature.update({field: int(getattr(item, field)) for field in ("width", "height", "depth", "arraysize", "mips", "msSamp")})
                signature["format"] = str(item.format.Name())
            elif kind == "buffer":
                signature["length"] = int(item.length)
            content = None
            if args.get("includeContentHashes"):
                if kind == "texture":
                    content = hashlib.sha256(bytes(self.controller.GetTextureData(item.resourceId, self.rd.Subresource()))).hexdigest()
                elif kind == "buffer":
                    content = hashlib.sha256(bytes(self.controller.GetBufferData(item.resourceId, 0, 0))).hexdigest()
                elif kind == "shader":
                    content = next((s["sha256"] for e in snapshot for s in e["state"]["shaders"].values() if s["resourceId"] == key), None)
            values.append(dict(desc, signature=signature, contentHash=content, usageSignatures=sorted(roles.get(key, [])), eventId=args["eventId"]))
        return {"resources": values, "contentScope": "Texture mip0/slice0/sample0 or entire buffer, at the specified event"}

    def dependency_data(self, args):
        events = {x["eventId"]: dict(x, reads=[], writes=[], possibleWrites=[]) for x in self.actions if x["leaf"] and x["eventId"] <= args["eventId"]}
        reads = {"VertexBuffer", "IndexBuffer", "InputTarget", "Indirect", "CopySrc", "ResolveSrc"}
        writes = {"ColorTarget", "DepthStencilTarget", "Clear", "CopyDst", "ResolveDst", "CPUWrite", "StreamOut"}
        for key, (_, resource, _) in self.resources.items():
            for usage in self.controller.GetUsage(resource.resourceId):
                event = events.get(int(usage.eventId))
                if event is None:
                    continue
                name = enum(usage.usage, self.rd.ResourceUsage)
                if name in reads or name.endswith("_Constants") or name.endswith("_Resource"):
                    event["reads"].append({"resourceId": key, "usage": name})
                if name in writes:
                    event["writes"].append({"resourceId": key, "usage": name})
                if name.endswith("_RWResource") or name in ("Copy", "Resolve", "GenMips"):
                    event["reads"].append({"resourceId": key, "usage": name})
                    event["possibleWrites"].append({"resourceId": key, "usage": name})
        return {"events": list(events.values()), "resources": {key: {"resourceId": key, "kind": value[0], "name": value[2]} for key, value in self.resources.items()}}

    def get_event_api_calls(self, args):
        self.get_action(args)
        event_map = {}
        for action in self.native_actions.values():
            for api in action.events:
                event_map[int(api.eventId)] = int(api.chunkIndex)
        ids = sorted(event_map)
        selected = next((i for i, event in enumerate(ids) if event >= args["eventId"]), len(ids))
        chosen = ids[max(0, selected - args.get("before", 10)):selected + args.get("after", 5) + 1]
        query = args.get("query", "").lower()
        chunks = [(event, self.structured.chunks[event_map[event]]) for event in chosen if event_map[event] < len(self.structured.chunks)]
        chunks = [(event, chunk) for event, chunk in chunks if query in str(chunk.name).lower()]
        offset, limit = args.get("offset", 0), args.get("limit", 30)
        def convert(obj, depth):
            kind = enum(obj.type.basetype, self.rd.SDBasic)
            result = {"name": str(obj.name), "type": str(obj.type.name), "kind": kind, "byteSize": int(obj.type.byteSize)}
            if kind in ("Chunk", "Struct", "Array"):
                total = int(obj.NumChildren())
                result["childCount"] = total
                if depth < args.get("maxDepth", 6):
                    count = min(total, args.get("arrayLimit", 32))
                    result["children"] = [convert(obj.GetChild(i), depth + 1) for i in range(count)]
                    result["truncated"] = count < total
                else:
                    result["truncated"] = bool(total)
            elif kind == "Resource":
                result["value"] = rid(obj.AsResourceId())
            elif kind == "Buffer":
                result["bufferIndex"] = int(obj.AsInt())
            else:
                # Python's documented SDObject convenience accessors differ
                # from the C++ AsUInt64/AsDouble methods hidden from SWIG.
                methods = {"String": "AsString", "Enum": "AsInt", "UnsignedInteger": "AsInt", "GPUAddress": "AsInt",
                           "SignedInteger": "AsInt", "Float": "AsFloat", "Boolean": "AsBool", "Character": "AsString"}
                method = methods.get(kind)
                if method:
                    result["value"] = plain(getattr(obj, method)())
                if obj.type.flags & self.rd.SDTypeFlags.HasCustomString:
                    result["display"] = str(obj.AsString())
            return result
        return {"eventId": args["eventId"], "total": len(chunks), "calls": [{"eventId": event, "chunkIndex": event_map[event],
                "name": str(chunk.name), "parameters": convert(chunk, 0)} for event, chunk in chunks[offset:offset + limit]],
                "nextOffset": offset + limit if offset + limit < len(chunks) else None}

    def list_gpu_counters(self, args):
        values = []
        for counter in self.controller.EnumerateCounters():
            desc = self.controller.DescribeCounter(counter)
            value = plain(desc)
            value.update(counterId=int(counter), resultType=enum(desc.resultType, self.rd.CompType), unit=enum(desc.unit, self.rd.CounterUnit))
            values.append(value)
        return {"counters": values}

    def profile_events(self, args):
        counters = self.list_gpu_counters({})["counters"]
        lookup = {x["counterId"]: x for x in counters}
        requested = args.get("counterIds", [int(self.rd.GPUCounter.EventGPUDuration)])
        missing = [x for x in requested if x not in lookup]
        if missing:
            raise ToolError("unsupported_counter", str(missing))
        native = list(self.controller.EnumerateCounters())
        selected = [x for x in native if int(x) in requested]
        started = time_monotonic()
        samples = self.controller.FetchCounters(selected)
        event_lookup = {x["eventId"]: x for x in self.actions}
        events, passes = {}, {}
        for sample in samples:
            event_id, counter_id = int(sample.eventId), int(sample.counter)
            if args.get("eventIds") and event_id not in args["eventIds"]:
                continue
            desc = lookup[counter_id]
            member = "d" if desc["resultType"] == "Float" and desc["resultByteWidth"] == 8 else "f" if desc["resultType"] == "Float" else "u64" if desc["resultByteWidth"] == 8 else "u32"
            number = plain(getattr(sample.value, member))
            invalid = (not isinstance(number, (float, int)) or
                       (isinstance(number, float) and not math.isfinite(number)) or number < 0 or
                       (member == "u64" and number == 2**64 - 1) or (member == "u32" and number == 2**32 - 1))
            action = event_lookup.get(event_id)
            aggregate = action and any(f in action.get("flags", "").split("|") for f in ("PushMarker", "PopMarker", "MultiAction"))
            value = {"counterId": counter_id, "value": None if invalid else number, "unit": desc["unit"], "valid": not invalid}
            events.setdefault(event_id, {"eventId": event_id, "action": action, "aggregateAction": bool(aggregate), "counters": []})["counters"].append(value)
            if counter_id == int(self.rd.GPUCounter.EventGPUDuration) and desc["unit"] == "Seconds" and desc["resultType"] == "Float" and not invalid:
                events[event_id]["durationMs"] = number * 1000
                ancestry = action["ancestry"] if action else []
                if not aggregate:
                    path = tuple(x["eventId"] for x in ancestry)
                    group = passes.setdefault(path, {"ancestry": ancestry, "durationMs": 0, "eventCount": 0})
                    group["durationMs"] += number * 1000
                    group["eventCount"] += 1
        ranked = sorted(events.values(), key=lambda x: x.get("durationMs", 0), reverse=True)
        from .convert import artifact
        full = {"events": ranked, "passes": sorted(passes.values(), key=lambda x: x["durationMs"], reverse=True),
                "counters": [lookup[x] for x in requested], "actions": self.actions,
                "interpretation": "Replay measurements; marker totals sum measured events, not live GPU wall time."}
        return {"counters": [lookup[x] for x in requested], "eventCount": len(ranked), "events": ranked[:args.get("limit", 30)],
                "passes": full["passes"], "fullResults": artifact(self.directory, json.dumps(full), "json", mimeType="application/json"),
                "fetchDurationMs": (time_monotonic() - started) * 1000,
                "interpretation": "GPU replay counter samples. Pass sums cover measured leaf events, not original live wall-clock duration."}


def time_monotonic():
    import time
    return time.monotonic()
