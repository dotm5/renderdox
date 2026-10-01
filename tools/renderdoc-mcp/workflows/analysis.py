"""Analysis orchestration and presentation, independent of native RenderDoc layouts."""
import asyncio
import copy
import csv
import hashlib
import io
import json
import math
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from contracts import ToolError
from .alignment import align
from .diff import image_artifact
from .shader_diff import compare_traces
from .reports import profile_report, evidence_report
from .doctor import diagnose, order_matrix_evidence

JOB_TOOLS = {"locate_draws_at_pixel", "visualize_draw_contribution", "preview_resources", "trace_output_dependencies",
             "group_related_draws", "profile_events", "match_resources", "track_constant_changes",
             "summarize_capture_changes", "export_analysis_bundle", "batch_query", "diff_shader_traces",
             "debug_pixel_pair", "export_profile_report", "capture_doctor"}


def file_artifact(directory, text, extension="json", role=None):
    path = Path(directory) / ("artifact-" + uuid.uuid4().hex + "." + extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8") if isinstance(text, str) else text
    path.write_bytes(data)
    return {"artifactId": path.stem, "path": str(path), "byteLength": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "mimeType": {"json": "application/json", "md": "text/markdown", "csv": "text/csv", "zip": "application/zip", "html": "text/html"}.get(extension, "text/plain"), "role": role}


def flatten_constants(stages):
    values = {}
    def visit(variable, prefix):
        path = prefix + "/" + variable["name"]
        if variable.get("members"):
            for child in variable["members"]:
                visit(child, path)
        else:
            values[path] = {key: variable.get(key) for key in ("type", "rows", "columns", "byteOffset", "values", "rawValue")}
    for stage in stages:
        for block in stage["blocks"]:
            for variable in block["variables"]:
                visit(variable, stage["stage"] + "/block" + str(block["index"]))
    return values


def font(size=14):
    for path in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def contact_sheet(items, args, directory):
    tile = max(64, args.get("tileSize", 256))
    columns = min(4, max(1, len(items)))
    height = tile + 72
    image = Image.new("RGB", (columns * tile, max(1, math.ceil(len(items) / columns)) * height), (25, 28, 34))
    draw, labels = ImageDraw.Draw(image), []
    for index, item in enumerate(items):
        x, y = index % columns * tile, index // columns * height
        if item.get("preview"):
            with Image.open(item["preview"]["image"]["path"]) as source:
                pixels = np.array(source.convert("RGBA"))
            channels = args.get("channels")
            if channels:
                if any(c not in range(4) for c in channels):
                    raise ToolError("invalid_channels", "Preview channels are indices 0..3")
                selected = pixels[..., channels]
                pixels = np.repeat(selected[..., :1], 3, axis=-1) if len(channels) == 1 else selected[..., :3]
                if pixels.shape[-1] == 2:
                    pixels = np.concatenate([pixels, np.zeros_like(pixels[..., :1])], -1)
            else:
                pixels = pixels[..., :3]
            preview = Image.fromarray(pixels)
            preview.thumbnail((tile - 12, tile - 12))
            image.paste(preview, (x + (tile - preview.width) // 2, y + (tile - preview.height) // 2))
        desc = item["resource"]["description"]
        identifier = item["resource"]["resourceId"]
        text = [identifier, "%dx%d %s" % (desc["width"], desc["height"], desc["formatName"]), item["resource"].get("name", "")[:32]]
        if item.get("error"):
            text[2] = "preview error: " + item["error"]["code"]
        for row, line in enumerate(text):
            draw.text((x + 6, y + tile + row * 20), line, font=font(12), fill=(225, 229, 237))
        labels.append({"resourceId": identifier, "rectangle": [x, y, x + tile, y + height]})
    return {"sheet": image_artifact(directory, np.array(image), "resource-contact-sheet"), "tiles": labels,
            "displayChannels": args.get("channels", [0, 1, 2]), "interpretation": "Display previews only; native bytes and formats remain available through read_texture."}


def contribution_images(raw, directory):
    images = []
    for index, comparison in enumerate(raw["comparisons"]):
        if comparison["status"] != "completed":
            images.append({"resourceId": raw["after"][index]["resourceId"], "status": "unsupported", "error": comparison.get("error")})
            continue
        with Image.open(comparison["heatmap"]["path"]) as heat:
            mask = np.array(heat.convert("RGB"))[..., 0] > 0
        preview = raw["previewsAfter"][index]
        with Image.open(preview["image"]["path"]) as source:
            background = np.array(source.convert("RGB"))
        if background.shape[:2] != mask.shape:
            raise ToolError("incompatible_dimensions", "Preview and numeric mask must have identical dimensions")
        overlay = background.copy()
        overlay[mask] = (background[mask].astype(float) * 0.35 + np.array([255, 65, 40]) * 0.65).astype(np.uint8)
        value = {"resourceId": raw["after"][index]["resourceId"], "changedPixels": comparison["changedPixels"],
                 "boundingBox": comparison["boundingBox"], "mask": image_artifact(directory, mask.astype(np.uint8) * 255, "draw-contribution-mask"),
                 "overlay": image_artifact(directory, overlay, "draw-contribution-overlay")}
        box = comparison["boundingBox"]
        if box:
            x0, y0 = max(0, box["x0"] - 16), max(0, box["y0"] - 16)
            x1, y1 = min(overlay.shape[1], box["x1"] + 16), min(overlay.shape[0], box["y1"] + 16)
            value["crop"] = image_artifact(directory, overlay[y0:y1, x0:x1], "draw-contribution-crop")
        images.append(value)
    return {"eventId": raw["eventId"], "preStateMethod": raw["preStateMethod"], "outputs": images,
            "diff": raw, "interpretation": "Changed output pixels at the selected event. This is not a semantic object mask or guaranteed final-screen visibility."}


def dependency_graph(dataset, args, directory):
    resources, events = dataset["resources"], dataset["events"]
    writers = {}
    for event in events:
        for item in event["writes"] + event["possibleWrites"]:
            writers.setdefault(item["resourceId"], []).append((event, item["usage"], item in event["possibleWrites"]))
    nodes, edges, visited = {}, [], set()
    truncated = False
    def visit(resource, before, depth):
        nonlocal truncated
        key = (resource, before)
        if key in visited:
            return
        visited.add(key)
        resource_node = "r" + resource.replace("ResourceId::", "") + "e" + str(before)
        nodes[resource_node] = {"id": resource_node, "type": "resource", "resourceId": resource, "atEvent": before, **resources.get(resource, {})}
        previous = [(event, usage, possible) for event, usage, possible in writers.get(resource, []) if event["eventId"] <= before]
        # Composite render targets can have many writers. Clear/copy/CPU write
        # forms an observable boundary; discard is not a defined new value.
        boundary = next((i for i in range(len(previous) - 1, -1, -1) if previous[i][1] in ("Clear", "CopyDst", "ResolveDst", "CPUWrite")), 0)
        if not previous:
            nodes[resource_node]["origin"] = "capture-initial-or-unrecorded-write"
        if depth >= args.get("maxDepth", 5) and previous:
            nodes[resource_node]["truncated"] = True
            truncated = True
            return
        for event, usage, possible in previous[boundary:]:
            event_node = "e" + str(event["eventId"])
            nodes[event_node] = {"id": event_node, "type": "event", "eventId": event["eventId"], "name": event["name"], "ancestry": event["ancestry"]}
            edge = {"from": event_node, "to": resource_node, "usage": usage, "certainty": "possible-write" if possible else "API-recorded-use"}
            if edge not in edges:
                edges.append(edge)
            for read in event["reads"]:
                read_node = "r" + read["resourceId"].replace("ResourceId::", "") + "e" + str(event["eventId"] - 1)
                edge = {"from": read_node, "to": event_node, "usage": read["usage"], "certainty": "resource-use"}
                if edge not in edges:
                    edges.append(edge)
                visit(read["resourceId"], event["eventId"] - 1, depth + 1)
    visit(args["resourceId"], args["eventId"], 0)
    lines = ["graph LR"]
    for node in nodes.values():
        label = "%s %s" % (node.get("eventId", node.get("resourceId")), node.get("name", ""))
        lines.append('  %s["%s"]' % (node["id"], label.replace('"', "'").replace("\n", " ")[:100]))
    for edge in edges:
        lines.append("  %s -->|%s| %s" % (edge["from"], edge["usage"], edge["to"]))
    offset, limit = args.get("offset", 0), args.get("limit", 100)
    node_list = list(nodes.values())
    return {"nodeCount": len(nodes), "edgeCount": len(edges), "nodes": node_list[offset:offset + limit], "edges": edges[offset:offset + limit], "truncated": truncated,
            "nextOffset": offset + limit if offset + limit < max(len(nodes), len(edges)) else None,
            "fullGraph": file_artifact(directory, json.dumps({"nodes": node_list, "edges": edges}), "json", "resource-dependency-graph"),
            "diagram": file_artifact(directory, "\n".join(lines), "mmd", "resource-dependency-graph"),
            "interpretation": "Backward API resource-use graph, including possible UAV writes and composite target history. It does not establish per-pixel shader dataflow."}


def related_draws(snapshot, args):
    reference = next((x for x in snapshot["events"] if x["eventId"] == args["eventId"]), None)
    if reference is None or "Drawcall" not in reference["flags"]:
        raise ToolError("missing_draw", str(args["eventId"]))
    candidates = []
    for event in snapshot["events"]:
        if event["eventId"] == reference["eventId"] or "Drawcall" not in event["flags"]:
            continue
        score, reasons = 0, []
        if reference["indexHash"] and reference["indexHash"] == event["indexHash"]:
            score += .42
            reasons.append("exact index range bytes")
        a, b = reference["state"], event["state"]
        if a["vertexBuffers"] and a["vertexBuffers"] == b["vertexBuffers"]:
            score += .3
            reasons.append("same capture-local vertex bindings")
        if reference.get("vertexHashes") and reference["vertexHashes"] == event.get("vertexHashes"):
            score += .3
            reasons.append("exact indexed vertex-span bytes")
        for field, weight in (("numIndices", .08), ("baseVertex", .04), ("numInstances", .03), ("instanceOffset", .03)):
            if reference[field] == event[field]:
                score += weight
                reasons.append(field + " equal")
        if a["topology"] == b["topology"]:
            score += .05
            reasons.append("topology equal")
        current = {"eventId": event["eventId"], "name": event["name"], "ancestry": event["ancestry"], "score": round(min(1, score), 4), "reasons": reasons,
                   "shaders": b["shaders"], "outputs": b["outputs"], "depth": b["depth"]}
        if "constants" in event:
            left, right = flatten_constants(reference["constants"]), flatten_constants(event["constants"])
            current["constantChanges"] = [{"path": path, "left": left.get(path), "right": right.get(path)} for path in sorted(set(left) | set(right)) if left.get(path) != right.get(path)]
        if current["score"] >= args.get("minScore", .5):
            candidates.append(current)
    return {"referenceEventId": args["eventId"], "reference": reference, "candidates": sorted(candidates, key=lambda x: x["score"], reverse=True),
            "interpretation": "Geometry candidates, not confirmed object identities. Instancing, shared meshes and different skinning/transform constants can represent distinct objects."}


def resource_matches(left, right, args):
    reference = [x for x in left["resources"] if not args.get("resourceIds") or x["resourceId"] in args["resourceIds"]]
    missing = set(args.get("resourceIds", [])) - {x["resourceId"] for x in reference}
    if missing:
        raise ToolError("missing_resource", str(sorted(missing)))
    mappings = []
    offset, limit = args.get("offset", 0), args.get("limit", 100)
    for resource in reference[offset:offset + limit]:
        candidates = []
        for target in right["resources"]:
            if resource["kind"] != target["kind"]:
                continue
            score, reasons = 0, []
            if resource["signature"] == target["signature"]:
                score += .25
                reasons.append("layout equal")
            if resource["contentHash"] and resource["contentHash"] == target["contentHash"]:
                score += .5
                reasons.append("sampled content equal")
            a, b = set(resource["usageSignatures"]), set(target["usageSignatures"])
            if a and b:
                similarity = len(a & b) / len(a | b)
                score += .22 * similarity
                if similarity:
                    reasons.append("shader/binding usage overlap %.3f" % similarity)
            if resource["name"] and resource["name"] == target["name"]:
                score += .03
                reasons.append("name equal")
            if score >= .2:
                candidates.append({"resourceId": target["resourceId"], "name": target["name"], "score": round(score, 5), "reasons": reasons})
        candidates.sort(key=lambda x: x["score"], reverse=True)
        clear = candidates and candidates[0]["score"] >= .65 and (len(candidates) < 2 or candidates[0]["score"] - candidates[1]["score"] >= .08)
        mappings.append({"resourceId": resource["resourceId"], "name": resource["name"], "status": "matched" if clear else "ambiguous" if candidates else "missing",
                         "targetResourceId": candidates[0]["resourceId"] if clear else None, "candidates": candidates[:args.get("candidateCount", 5)]})
    return {"total": len(reference), "mappings": mappings, "nextOffset": offset + limit if offset + limit < len(reference) else None,
            "contentScope": left["contentScope"], "interpretation": "Evidence-ranked candidates; changing content can still be the same logical resource. ResourceId numeric equality is not a matching feature."}


def trace_query(payload, args):
    variable, query = args.get("variable", "").lower(), args.get("query", "").lower()
    mode = args.get("mode", "changes")
    if mode not in ("changes", "steps", "last_write"):
        raise ToolError("invalid_mode", mode)
    records = []
    for step in payload.get("steps", []):
        index = step.get("stepIndex", 0)
        if not args.get("minStep", 0) <= index <= args.get("maxStep", 2**32 - 1):
            continue
        if "instruction" in args and step.get("nextInstruction") != args["instruction"]:
            continue
        if args.get("flags", "").lower() not in str(step.get("flags", "")).lower():
            continue
        changes = [x for x in step.get("changes", []) if variable in str(x.get("after", {}).get("name", x.get("before", {}).get("name", ""))).lower()]
        if variable and not changes:
            continue
        value = dict(step, changes=changes)
        if query and query not in json.dumps(value).lower():
            continue
        records.append(value)
    if mode == "last_write":
        records = [x for x in records if x["changes"]][-1:]
    offset, limit = args.get("offset", 0), args.get("limit", 40)
    return {"total": len(records), "steps": records[offset:offset + limit], "nextOffset": offset + limit if offset + limit < len(records) else None,
            "interpretation": "Recorded mutable variable changes; nextInstruction is the instruction after the state. No inferred dependency slice or texture-sample operands."}


def constant_timeline(samples, args, directory):
    paths = sorted({path for sample in samples for path in sample.get("values", {}) if args.get("query", "").lower() in path.lower()})
    series = []
    for path in paths:
        values = [x.get("values", {}).get(path) for x in samples]
        available = [v for v in values if v is not None]
        changed = len(available) > 1 and any(v != available[0] for v in available[1:])
        maximum = 0
        for a, b in zip(values, values[1:]):
            if a and b and a.get("values") and b.get("values") and a["type"] == b["type"]:
                deltas = [abs(float(x) - float(y)) for x, y in zip(a["values"], b["values"]) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
                maximum = max([maximum] + deltas)
        series.append({"path": path, "changed": changed, "maxAdjacentDelta": maximum, "samples": values})
    series.sort(key=lambda x: (x["changed"], x["maxAdjacentDelta"]), reverse=True)
    chosen = series[:args.get("limit", 30)]
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["captureId", "frameNumber", "captureTimestamp", "eventId", "path", "type", "byteOffset", "values"])
    for curve in series:
        for sample, value in zip(samples, curve["samples"]):
            writer.writerow([sample["captureId"], sample.get("frameNumber"), sample.get("timestamp"), sample.get("eventId"), curve["path"],
                             value.get("type") if value else None, value.get("byteOffset") if value else None, json.dumps(value.get("values")) if value else "missing"])
    result = {"samples": [{k: v for k, v in x.items() if k != "values"} for x in samples], "totalVariables": len(series),
              "changedVariables": sum(x["changed"] for x in series), "series": chosen,
              "csv": file_artifact(directory, stream.getvalue(), "csv", "constant-timeline"),
              "fullResults": file_artifact(directory, json.dumps({"samples": samples, "series": series}), "json", "constant-timeline"),
              "interpretation": "Capture-set order with frame/timestamp metadata; gaps and ambiguous alignments remain missing. Constant offsets have no inferred material semantics."}
    plot = [curve for curve in chosen if any(value and value.get("values") for value in curve["samples"])][:8]
    if plot:
        image = Image.new("RGB", (1000, 140 * len(plot)), (25, 28, 34))
        draw = ImageDraw.Draw(image)
        palette = [(90, 180, 255), (255, 160, 90), (120, 220, 150), (230, 120, 210)]
        for row, curve in enumerate(plot):
            top = row * 140
            draw.text((12, top + 6), curve["path"], fill="white", font=font(13))
            numbers = [float(v) for value in curve["samples"] if value for v in value.get("values", []) if isinstance(v, (int, float)) and math.isfinite(v)]
            if not numbers:
                continue
            lo, hi = min(numbers), max(numbers)
            draw.text((12, top + 28), "range %.6g .. %.6g; x=capture order" % (lo, hi), fill=(190, 194, 200), font=font(12))
            components = max((len(value.get("values", [])) for value in curve["samples"] if value), default=0)
            for component in range(components):
                previous = None
                for index, value in enumerate(curve["samples"]):
                    values = value.get("values", []) if value else []
                    if component >= len(values) or not isinstance(values[component], (int, float)) or not math.isfinite(values[component]):
                        previous = None
                        continue
                    point = (220 + index * 750 / max(1, len(samples) - 1), top + 122 - (values[component] - lo) / (hi - lo or 1) * 65)
                    if previous:
                        draw.line([previous, point], fill=palette[component % len(palette)], width=2)
                    draw.ellipse([point[0]-3, point[1]-3, point[0]+3, point[1]+3], fill=palette[component % len(palette)])
                    previous = point
        result["chart"] = image_artifact(directory, np.array(image), "constant-timeline-chart")
    return result


def project(value, fields):
    if not fields:
        return value
    result = {}
    for field in fields:
        item = value
        try:
            for segment in field.split("."):
                item = item[int(segment)] if isinstance(item, list) else item[segment]
            result[field] = item
        except (KeyError, IndexError, ValueError, TypeError):
            result[field] = {"unavailable": "field not returned"}
    return result


class AnalysisWorkflows:
    def load_json_artifact(self, key, limit=268435456):
        item = self.get(self.db["artifacts"], key, "artifact")
        path = Path(item["path"])
        if path.stat().st_size > limit:
            raise ToolError("artifact_too_large", str(path))
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest().lower() != item["sha256"].lower():
            raise ToolError("artifact_changed", key)
        return json.loads(raw)

    async def analysis_diff_shader_traces(self, args, info, stop):
        def run():
            left = self.load_json_artifact(args["leftArtifactId"])
            right = self.load_json_artifact(args["rightArtifactId"])
            result = compare_traces(left, right, args)
            result.update(leftArtifactId=args["leftArtifactId"], rightArtifactId=args["rightArtifactId"])
            result["fullResults"] = file_artifact(self.output / "trace-diffs", json.dumps(result, allow_nan=False), role="shader-trace-diff")
            return result
        return await asyncio.to_thread(run)

    async def analysis_debug_pixel_pair(self, args, info, stop):
        from contracts.catalog import validate
        sides = [dict(args[k], stage="Pixel") for k in ("left", "right")]
        for side in sides:
            validate("debug_shader", side)
            if "x" not in side or "y" not in side:
                raise ToolError("invalid_arguments", "Each side needs sessionId, eventId, x and y")
        results = []
        for side in sides:
            if stop.is_set():
                return {"recordedTraces": results, "status": "cancelled"}
            results.append(await self.query("debug_shader", side))
            info["progress"] = len(results) / 3
        comparison = await self.analysis_diff_shader_traces(dict(args, leftArtifactId=results[0]["trace"]["artifactId"],
                                                               rightArtifactId=results[1]["trace"]["artifactId"]), info, stop)
        comparison["recordedTraces"] = results
        return comparison

    async def analysis_export_profile_report(self, args, info, stop):
        query = {k: v for k, v in args.items() if k != "title"}
        result = await self.query("profile_events", query)
        info["progress"] = .6
        if stop.is_set():
            return {"profile": result, "status": "cancelled"}
        def render():
            payload = self.load_json_artifact(result["fullResults"]["artifactId"])
            payload["identity"] = {"captureId": result["captureId"], "sessionId": args["sessionId"], "measurement": "GPU replay"}
            return file_artifact(self.output / "reports", profile_report(payload, args.get("title", "RenderDoc replay performance")), "html", "profile-report")
        return {"profile": result, "report": await asyncio.to_thread(render)}

    async def analysis_capture_doctor(self, args, info, stop):
        if not any(args.get(k) for k in ("connectionId", "captureId", "sessionId", "orderMatrixPath")):
            raise ToolError("invalid_arguments", "Select connectionId, captureId, sessionId or orderMatrixPath")
        connection = capture = replay = health = None
        errors = []
        if args.get("connectionId"):
            try:
                connection = await self.connection_query("get_connection", {"connectionId": args["connectionId"]})
            except ToolError as exc:
                errors.append(dict(exc.payload(), scope="connection"))
        capture_id = args.get("captureId")
        session = args.get("sessionId")
        if session:
            session_capture = self.get(self.sessions, session, "session")["captureId"]
            if capture_id and capture_id != session_capture:
                raise ToolError("capture_session_mismatch", "sessionId does not belong to captureId")
            capture_id = session_capture
        owned = False
        if capture_id:
            capture = copy.deepcopy(self.get(self.db["captures"], capture_id, "capture"))
            try:
                from supervisor.service import sha256
                if (await asyncio.to_thread(sha256, capture["path"])).lower() != capture["sha256"].lower():
                    raise ToolError("capture_changed", "Collected capture bytes no longer match captureId")
                if not session:
                    session, owned = await self.session_for(capture_id)
                replay = await self.query("get_capture_summary", {"sessionId": session})
            except (ToolError, OSError) as exc:
                error = exc.payload() if isinstance(exc, ToolError) else {"code": "capture_unavailable", "message": str(exc)}
                errors.append(dict(error, scope="replay"))
            finally:
                if owned:
                    await self.close_session(session)
        if args.get("healthArtifactId"):
            health = await asyncio.to_thread(self.load_json_artifact, args["healthArtifactId"], 8 * 1024 * 1024)
        elif args.get("healthReportPath"):
            path = Path(args["healthReportPath"])
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ToolError("artifact_too_large", "Health report exceeds 8 MiB")
            health = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8-sig"))
        result = diagnose(connection, capture, replay, health, errors)
        if args.get('orderMatrixPath'):
            from supervisor.service import sha256
            core_hash = await asyncio.to_thread(sha256, self.package_root / 'dgcore.dll')
            try:
                result['orderMatrixEvidence'] = await asyncio.to_thread(order_matrix_evidence, args['orderMatrixPath'], core_hash)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ToolError('invalid_order_matrix', str(exc))
        result["fullResults"] = file_artifact(self.output / "doctor", json.dumps(result, allow_nan=False), role="capture-doctor")
        return result

    def analysis_job(self, name, args):
        async def run(info, stop):
            result = await getattr(self, "analysis_" + name)(args, info, stop)
            self.register(result)
            self.save()
            return result
        return self.job(name, run)

    async def analysis_locate_draws_at_pixel(self, args, info, stop):
        return await self.query("locate_draws_at_pixel", args)

    async def analysis_visualize_draw_contribution(self, args, info, stop):
        raw = await self.call("diff_event", dict(args, displayImages=True))
        return await asyncio.to_thread(contribution_images, raw, self.output / "contributions")

    async def analysis_preview_resources(self, args, info, stop):
        resources = await self.query("list_resources", {"sessionId": args["sessionId"], "kind": "texture", "query": args.get("query", ""), "limit": 100000})
        filtered = [x for x in resources["resources"] if not args.get("resourceIds") or x["resourceId"] in args["resourceIds"]]
        offset, limit = args.get("offset", 0), args.get("limit", 16)
        items = []
        for resource in filtered[offset:offset + limit]:
            if stop.is_set():
                break
            item = {"resource": resource}
            params = {key: value for key, value in args.items() if key in ("sessionId", "eventId", "mip", "slice", "sample", "blackPoint", "whitePoint")}
            try:
                item["preview"] = await self.query("view_texture", dict(params, resourceId=resource["resourceId"]))
                usage = await self.query("trace_resource_flow", {"sessionId": args["sessionId"], "resourceId": resource["resourceId"]})
                item["usage"] = usage["usage"]
            except ToolError as exc:
                item["error"] = exc.payload()
            items.append(item)
            info["progress"] = len(items) / max(1, min(limit, len(filtered) - offset))
        result = await asyncio.to_thread(contact_sheet, items, args, self.output / "contact-sheets")
        return dict(result, resources=items, total=len(filtered), nextOffset=offset + limit if offset + limit < len(filtered) else None)

    async def analysis_trace_output_dependencies(self, args, info, stop):
        data = await self.query("dependency_data", {"sessionId": args["sessionId"], "eventId": args["eventId"]})
        if args["resourceId"] not in data["resources"]:
            raise ToolError("missing_resource", args["resourceId"])
        return await asyncio.to_thread(dependency_graph, data, args, self.output / "graphs")

    async def analysis_group_related_draws(self, args, info, stop):
        snapshot = await self.query("analysis_snapshot", {key: value for key, value in args.items() if key in ("sessionId", "includeConstants", "includeGeometryHashes")})
        return await asyncio.to_thread(related_draws, snapshot, args)

    async def analysis_profile_events(self, args, info, stop):
        return await self.query("profile_events", args)

    async def analysis_match_resources(self, args, info, stop):
        common = {key: value for key, value in args.items() if key in ("kind", "includeContentHashes")}
        left = await self.query("resource_fingerprints", dict(common, sessionId=args["leftSessionId"], eventId=args["leftEventId"]))
        info["progress"] = .5
        right = await self.query("resource_fingerprints", dict(common, sessionId=args["rightSessionId"], eventId=args["rightEventId"]))
        return await asyncio.to_thread(resource_matches, left, right, args)

    async def analysis_track_constant_changes(self, args, info, stop):
        alignment = self.get(self.db["alignments"], args["alignmentId"], "alignment")
        collection = self.get(self.db["sets"], alignment["captureSetId"], "capture_set")
        samples = []
        for capture_id in collection["captureIds"]:
            if stop.is_set():
                break
            capture = self.get(self.db["captures"], capture_id, "capture")
            sample = {"captureId": capture_id, "frameNumber": capture.get("frameNumber"), "timestamp": capture.get("timestamp")}
            owned, session = False, None
            try:
                event = args["eventId"] if capture_id == alignment["referenceCaptureId"] else self.match(args["alignmentId"], args["eventId"], capture_id)[1]
                session, owned = await self.session_for(capture_id)
                params = {key: value for key, value in args.items() if key in ("stage", "blockIndex")}
                constants = await self.query("get_constants", dict(params, sessionId=session, eventId=event))
                sample.update(eventId=event, values=flatten_constants([constants]))
            except ToolError as exc:
                sample["error"] = exc.payload()
            finally:
                if owned:
                    await self.close_session(session)
            samples.append(sample)
            info["progress"] = len(samples) / len(collection["captureIds"])
        return await asyncio.to_thread(constant_timeline, samples, args, self.output / "timelines")

    async def analysis_summarize_capture_changes(self, args, info, stop):
        common = {key: value for key, value in args.items() if key in ("minEventId", "maxEventId", "includeConstants")}
        left = await self.query("analysis_snapshot", dict(common, sessionId=args["leftSessionId"]))
        right = await self.query("analysis_snapshot", dict(common, sessionId=args["rightSessionId"]))
        def signatures(snapshot):
            return [dict(event, shaders={key: value["sha256"] for key, value in event["state"]["shaders"].items()},
                         topology=event["state"]["topology"], outputDescriptions=[]) for event in snapshot["events"]]
        mapping = await asyncio.to_thread(align, signatures(left), signatures(right))
        right_by_id = {x["eventId"]: x for x in right["events"]}
        matched, ambiguous, missing, used = [], [], [], set()
        for event in left["events"]:
            match = mapping["events"][str(event["eventId"])]
            if match["status"] != "matched" or match.get("relation") == "many-to-one":
                (missing if match["status"] == "missing" else ambiguous).append({"eventId": event["eventId"], "alignment": match})
                continue
            target = right_by_id[match["targetEventIds"][0]]
            used.add(target["eventId"])
            a, b = event["state"], target["state"]
            changes = []
            for field in ("shaders", "topology", "vertexInputs", "depthTest", "colorBlend", "viewports", "scissors"):
                va, vb = a[field], b[field]
                if field == "shaders":
                    va, vb = {k: v["sha256"] for k, v in va.items()}, {k: v["sha256"] for k, v in vb.items()}
                if va != vb:
                    changes.append({"field": field, "left": va, "right": vb})
            # Binding layouts are comparable; raw cross-capture ResourceIds are not.
            def layout(state):
                return [{k: v for k, v in binding.items() if k not in ("resourceId", "access")} for binding in state["bindings"]]
            if layout(a) != layout(b):
                changes.append({"field": "bindingLayouts", "left": layout(a), "right": layout(b)})
            constant_differences = []
            if args.get("includeConstants"):
                av, bv = flatten_constants(event["constants"]), flatten_constants(target["constants"])
                constant_differences = [{"path": path, "left": av.get(path), "right": bv.get(path)} for path in sorted(set(av) | set(bv)) if av.get(path) != bv.get(path)]
            matched.append({"leftEventId": event["eventId"], "rightEventId": target["eventId"], "score": match["candidates"][0]["score"],
                            "stateChanges": changes, "constantChanges": constant_differences})
        requested = matched[:args.get("limit", 30)]
        if args.get("includeOutputDiffs"):
            for index, entry in enumerate(requested):
                if stop.is_set():
                    break
                a = next(x for x in left["events"] if x["eventId"] == entry["leftEventId"])["state"]["outputs"]
                b = right_by_id[entry["rightEventId"]]["state"]["outputs"]
                entry["outputDiffs"] = []
                for slot, (out_a, out_b) in enumerate(zip(a, b)):
                    if not out_a.get("resource") or not out_b.get("resource"):
                        continue
                    try:
                        diff = await self.diff_pair({"leftSessionId": args["leftSessionId"], "leftEventId": entry["leftEventId"], "leftResourceId": out_a["resource"],
                                                    "rightSessionId": args["rightSessionId"], "rightEventId": entry["rightEventId"], "rightResourceId": out_b["resource"], "displayImages": False})
                        entry["outputDiffs"].append(dict(diff, outputIndex=slot))
                    except ToolError as exc:
                        entry["outputDiffs"].append({"outputIndex": slot, "error": exc.payload()})
                info["progress"] = (index + 1) / max(1, len(requested))
        full = {"matched": matched, "ambiguous": ambiguous, "unmatchedLeft": missing,
                "unresolvedRightEventIds": sorted(set(right_by_id) - used)}
        return {"matchedCount": len(matched), "stateChangedCount": sum(bool(x["stateChanges"]) for x in matched),
                "constantsChangedCount": sum(bool(x["constantChanges"]) for x in matched), "matched": requested,
                "ambiguousCount": len(ambiguous), "ambiguous": ambiguous[:args.get("limit", 30)], "unmatchedLeft": missing,
                "unresolvedRightEventIds": full["unresolvedRightEventIds"], "fullResults": file_artifact(self.output / "changes", json.dumps(full), "json"),
                "interpretation": "Unmatched or ambiguous events are not proven object additions/removals. Binding layout changes do not establish resource content identity."}

    async def analysis_batch_query(self, args, info, stop):
        allowed = {"get_capture_summary", "find_actions", "get_action", "list_resources", "get_pipeline_state", "get_draw_evidence", "get_shader", "get_constants",
                   "get_buffer_data", "view_texture", "read_texture", "sample_pixels", "get_mesh", "get_post_vs_data", "get_resource_usage", "trace_resource_flow",
                   "pixel_history", "get_event_api_calls", "list_gpu_counters", "list_annotations", "get_aligned_event", "get_capabilities"}
        results = []
        for index, query in enumerate(args["queries"]):
            if stop.is_set():
                break
            started = time.monotonic()
            try:
                if not isinstance(query, dict) or query.get("tool") not in allowed:
                    raise ToolError("invalid_batch_query", "Use a supported read query with tool, arguments and optional fields")
                value = await self.call(query["tool"], query.get("arguments", {}))
                results.append({"index": index, "tool": query["tool"], "result": project(value, query.get("fields")), "durationMs": (time.monotonic()-started)*1000})
            except (ToolError, TypeError, ValueError) as exc:
                results.append({"index": index, "error": exc.payload() if isinstance(exc, ToolError) else {"code": type(exc).__name__, "message": str(exc)}})
            info["progress"] = len(results) / max(1, len(args["queries"]))
        return {"results": results, "requested": len(args["queries"]), "completed": len(results), "ordering": "request order; native calls serialized per worker"}

    def annotate(self, args):
        self.get(self.db["captures"], args["captureId"], "capture")
        annotation_id = args.get("annotationId") or "annotation-" + uuid.uuid4().hex
        if args.get("annotationId"):
            old = self.get(self.db["annotations"], annotation_id, "annotation")
            if old["captureId"] != args["captureId"]:
                raise ToolError("annotation_capture_mismatch", annotation_id)
        value = dict(self.db["annotations"].get(annotation_id, {}), **args, annotationId=annotation_id, updatedAt=time.time())
        value.setdefault("createdAt", time.time())
        self.db["annotations"][annotation_id] = value
        self.save()
        return value

    def annotations(self, args):
        return {"annotations": [copy.deepcopy(value) for value in self.db["annotations"].values() if all(value.get(key) == args[key] for key in ("captureId", "eventId", "resourceId") if key in args)
                                and (not args.get("tag") or args["tag"] in value.get("tags", []))]}

    async def query_trace(self, args):
        artifact = self.get(self.db["artifacts"], args["artifactId"], "artifact")
        def run():
            payload = json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or "steps" not in payload:
                raise ToolError("invalid_trace", "Choose an artifact returned by debug_shader")
            return trace_query(payload, args)
        return await asyncio.to_thread(run)

    async def analysis_export_analysis_bundle(self, args, info, stop):
        capture = copy.deepcopy(self.get(self.db["captures"], args["captureId"], "capture"))
        session, owned = await self.session_for(args["captureId"])
        try:
            summary = await self.query("get_capture_summary", {"sessionId": session})
            evidence = []
            for event in args.get("eventIds", []):
                if stop.is_set():
                    break
                evidence.append(await self.query("get_draw_evidence", {"sessionId": session, "eventId": event, "includeConstants": args.get("includeConstants", True), "includePreviews": True}))
            notes = self.annotations({"captureId": args["captureId"]})["annotations"]
            artifacts = [copy.deepcopy(self.get(self.db["artifacts"], key, "artifact")) for key in args.get("artifactIds", [])]
            def collect(value):
                if isinstance(value, dict):
                    if "artifactId" in value and "path" in value:
                        artifacts.append(value)
                    for child in value.values():
                        collect(child)
                elif isinstance(value, list):
                    for child in value:
                        collect(child)
            collect(summary)
            collect(evidence)
            payload = {"capture": capture, "summary": summary, "annotations": notes, "evidence": evidence}
            return await asyncio.to_thread(export_bundle, payload, artifacts, args, self.output / "bundles")
        finally:
            if owned:
                await self.close_session(session)


def export_bundle(payload, artifacts, args, directory):
    artifacts = list(artifacts)
    def collect(value):
        if isinstance(value, dict):
            if "artifactId" in value and "path" in value:
                artifacts.append(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(payload)
    root = Path(directory) / ("bundle-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    copied, unique = {}, {a["artifactId"]: a for a in artifacts}
    for key, value in unique.items():
        source = Path(value["path"])
        destination = root / "artifacts" / (key + source.suffix)
        destination.parent.mkdir(exist_ok=True)
        shutil.copy2(source, destination)
        copied[key] = str(destination.relative_to(root)).replace("\\", "/")
    def portable(value):
        if isinstance(value, dict):
            return {key: copied.get(value.get("artifactId"), item) if key == "path" else portable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [portable(item) for item in value]
        return value
    content = portable(payload)
    if args.get("includeRdc", False):
        shutil.copy2(payload["capture"]["path"], root / "capture.rdc")
        content["capture"]["path"] = "capture.rdc"
    else:
        content["capture"]["path"] = None
        content["capture"]["rdcIncluded"] = False
    content["summary"].pop("path", None)
    # Resource alpha has data meaning; browsers must not use it as opacity for
    # a framebuffer RGB preview. Keep the original artifact bytes untouched.
    for evidence in content.get("evidence", []):
        for preview in evidence.get("previews", []):
            original = preview["image"]
            target = root / "display-previews" / (original["artifactId"] + ".png")
            target.parent.mkdir(exist_ok=True)
            with Image.open(root / original["path"]) as image:
                image.convert("RGB").save(target)
            preview["displayImage"] = {
                "path": target.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "sourceArtifactId": original["artifactId"], "sourceSHA256": original["sha256"],
                "transform": "Preserve preview RGB; discard stored alpha for opaque display. No extra color transfer."}
    (root / "analysis.json").write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = payload["summary"]
    lines = ["# " + args.get("title", "RenderDoc analysis evidence"), "", "Capture: `%s`" % payload["capture"]["sha256"],
             "", "API: %s; frame: %s; actions: %s." % (summary["api"], summary["frame"].get("frameNumber"), summary["actionCount"]), "", "## Notes", ""]
    for note in payload["annotations"]:
        lines += ["- EID %s / %s: %s" % (note.get("eventId", "-"), note.get("resourceId", "-"), note["note"])]
    lines += ["", "## Events", ""]
    for evidence in content["evidence"]:
        action = evidence["action"]
        lines += ["### EID %s: %s" % (action["eventId"], action["name"]), "", "Indices: %s; flags: %s." % (action["numIndices"], action["flags"]), ""]
        for preview in evidence.get("previews", []):
            lines += ["![%s](%s)" % (preview["resourceId"], preview["displayImage"]["path"]), ""]
    lines += ["## Attached artifacts", ""]
    for key, path in copied.items():
        lines.append("- [%s](%s)" % (key, path))
    report = root / "REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    html_report = root / "REPORT.html"
    html_report.write_text(evidence_report(content, copied, args.get("title", "RenderDoc analysis evidence")), encoding="utf-8")
    archive = root.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in root.rglob("*"):
            if path.is_file():
                output.write(path, str(path.relative_to(root)))
    def describe(path, mime):
        return {"artifactId": "artifact-" + uuid.uuid4().hex, "path": str(path), "byteLength": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mimeType": mime}
    return {"directory": str(root), "report": describe(report, "text/markdown"), "htmlReport": describe(html_report, "text/html"), "index": describe(root / "analysis.json", "application/json"),
            "archive": describe(archive, "application/zip"), "artifactCount": len(copied), "rdcIncluded": args.get("includeRdc", False)}
