"""Tool discovery is generated from the same contracts used for validation."""
S = {"type": "string"}
I = {"type": "integer", "minimum": 0}
N = {"type": "number", "minimum": 0}
B = {"type": "boolean"}
O = {"type": "object"}
A = {"type": "array"}
TOOLS = {}


def add(tool_name, description, required=(), **properties):
    TOOLS[tool_name] = {"name": tool_name, "description": description,
                   "inputSchema": {"type": "object", "properties": properties,
                                   "required": list(required), "additionalProperties": False}}


add("get_capabilities", "Report package identity, worker ABI and actual backend capabilities.", sessionId=S)
add("list_targets", "Discover RenderDoc-enabled targets; existing GUI connections are not taken over.", host=S)
add("connect_target", "Connect to a discovered target. takeover=true explicitly replaces an existing controller.",
    ("targetId",), targetId=S, takeover=B, clientName=S)
for name, description in [("disconnect_target", "Disconnect without terminating the application."),
                          ("get_connection", "Connection, capture progress and received messages."),
                          ("cycle_capture_window", "Cycle the target's active capture window.")]:
    add(name, description, ("connectionId",), connectionId=S)
for name, description in [("capture_now", "Request consecutive RDC frames and collect them into persistent storage."),
                          ("capture_after", "Request capture after delaySeconds."),
                          ("capture_at_frame", "Queue capture at the target frame boundary."),
                          ("capture_sequence", "Schedule count capture rounds, delaying the next round while one is pending.")]:
    add(name, description + " Returns jobId; get_job tracks completion and ambiguous attribution.",
        ("connectionId",), connectionId=S, framesPerCapture={**I, "minimum": 1},
        count={**I, "minimum": 1}, intervalSeconds=N, delaySeconds=N, frameNumber=I,
        completionTimeoutSeconds={**N, "exclusiveMinimum": 0}, captureSetId=S)
add("list_captures", "List persistent captures or captures reported by a connection.", connectionId=S)
add("save_capture", "Collect a connection capture into persistent storage; returns jobId.",
    ("connectionId", "remoteCaptureId"), connectionId=S, remoteCaptureId=I)
add("get_job", "Inspect queued/running/completed/failed/cancelled job, timing and result.", ("jobId",), jobId=S)
add("stop_job", "Request cooperative stop; in-flight native calls finish before cleanup.", ("jobId",), jobId=S)
add("launch_and_capture", "Launch with RenderDoc injection and return a control connection. Does not wait for target exit.",
    ("application",), application=S, workingDirectory=S, commandLine=S, environment=A,
    captureOptions=O, captureFile=S)
add("inject_process", "Inject RenderDoc into a specified PID and return a control connection.",
    ("pid",), pid={**I, "minimum": 1}, environment=A, captureOptions=O, captureFile=S)
add("open_capture", "Open a persistent RDC in a dedicated replay worker. Returns jobId and then sessionId.", path=S, captureId=S)
add("close_capture", "Close replay through its serial queue; leaves the target connected.", ("sessionId",), sessionId=S)
add("get_capture_summary", "API, frame, action and resource counts, thumbnail, actual support.", ("sessionId",), sessionId=S)
add("find_actions", "Filter actions by name, flags or EID range; includes marker ancestry.",
    ("sessionId",), sessionId=S, query=S, flags=S, minEventId=I, maxEventId=I, offset=I, limit=I)
add("get_action", "Retrieve action and marker ancestry.", ("sessionId", "eventId"), sessionId=S, eventId=I)
add("list_resources", "Resource names, IDs and buffer/texture descriptions; filter before exporting.",
    ("sessionId",), sessionId=S, kind=S, query=S, offset=I, limit=I)
for name, description in [("get_pipeline_state", "All shader stages, descriptors, output/depth and input state."),
                          ("get_draw_evidence", "One atomic event query combining bindings, constants, mesh and output previews.")]:
    add(name, description, ("sessionId", "eventId"), sessionId=S, eventId=I, includeConstants=B, includePreviews=B)
add("get_shader", "Reflection, raw bytecode artifact and paged/searchable disassembly.",
    ("sessionId", "eventId", "stage"), sessionId=S, eventId=I, stage=S,
    includeBytecode=B, includeDisassembly=B, lineOffset=I, lineCount=I, search=S)
add("get_constants", "Read reflected constants using descriptor byteOffset/byteSize; optionally raw bytes.",
    ("sessionId", "eventId", "stage"), sessionId=S, eventId=I, stage=S, blockIndex=I, arrayIndex=I, includeRaw=B)
add("get_buffer_data", "Export exact buffer range; optional f32/u32/i32/u16/u8 scalar decoding.",
    ("sessionId", "eventId", "resourceId"), sessionId=S, eventId=I, resourceId=S, offset=I, length=I, decode=S)
for name, description in [("view_texture", "Export PNG/EXR/DDS with explicit display mapping; PNG is a preview."),
                          ("read_texture", "Export untransformed bytes for one mip/slice/sample; 3D returns the entire mip.")]:
    add(name, description, ("sessionId", "eventId", "resourceId"), sessionId=S, eventId=I, resourceId=S,
        mip=I, slice=I, sample=I, fileType=S, blackPoint={"type": "number"}, whitePoint={"type": "number"})
add("sample_pixels", "Read actual pixel values at points via the replay API, not PNG colors.",
    ("sessionId", "eventId", "resourceId", "points"), sessionId=S, eventId=I, resourceId=S,
    points={"type": "array", "items": {"type": "array", "items": I, "minItems": 2, "maxItems": 2}},
    mip=I, slice=I, sample=I, typeCast=S)
add("get_mesh", "Vertex/index bindings and attributes; optional exact input buffer artifacts.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, includeData=B)
add("get_post_vs_data", "Post-transform geometry layout and data for a chosen instance/view/stage.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, instance=I, view=I, stage=S, includeData=B)
for name, description in [("get_resource_usage", "API-reported resource usage across the frame."),
                          ("trace_resource_flow", "Resource usages joined to actions and marker ancestry.")]:
    add(name, description, ("sessionId", "resourceId"), sessionId=S, resourceId=S)
add("pixel_history", "Pixel modifications with failure reasons for the current API.",
    ("sessionId", "eventId", "resourceId", "x", "y"), sessionId=S, eventId=I, resourceId=S,
    x=I, y=I, mip=I, slice=I, sample=I, typeCast=S)
add("debug_shader", "Debug Pixel/Vertex/Compute and export the full trace; frees native trace in finally.",
    ("sessionId", "eventId", "stage"), sessionId=S, eventId=I, stage=S, x=I, y=I,
    vertex=I, instance=I, index=I, view=I, group=A, thread=A, sample=I, primitive=I)
add("replace_shader", "Build and install a shader replacement. Compilation diagnostics are returned.",
    ("sessionId", "eventId", "stage", "encoding"), sessionId=S, eventId=I, stage=S,
    encoding=S, source=S, sourceFile=S, entryPoint=S, compileFlags=A)
add("restore_replacement", "Restore one shader or all replacements and free replacement shaders.",
    ("sessionId",), sessionId=S, resourceId=S)
add("diff_event", "Compare the same output immediately before/after an actual leaf action; includes depth/UAV on request.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, resourceIds=A, mip=I, slice=I, sample=I,
    threshold=N, relativeThreshold=N, roi=A, channels=A, displayImages=B)
add("diff_captures", "Compare explicitly corresponding event/resources from two RDCs, without implicit resizing.",
    ("leftSessionId", "leftEventId", "leftResourceId", "rightSessionId", "rightEventId", "rightResourceId"),
    leftSessionId=S, leftEventId=I, leftResourceId=S, rightSessionId=S, rightEventId=I, rightResourceId=S,
    mip=I, slice=I, sample=I, threshold=N, relativeThreshold=N, roi=A, channels=A, displayImages=B)
add("create_capture_set", "Persist an ordered capture collection; order alone does not establish temporal continuity.",
    ("captureIds",), captureIds=A, name=S, referenceCaptureId=S, temporal=B)
add("list_capture_sets", "List saved ordered collections.")
add("align_events", "Align pass/leaf actions across a collection using shader hashes, topology, outputs and draw features.",
    ("captureSetId",), captureSetId=S, referenceCaptureId=S, includeTextureHashes=B)
add("get_aligned_event", "Return scored candidates and manual anchors for a reference event.",
    ("alignmentId", "eventId"), alignmentId=S, eventId=I, captureId=S)
add("override_alignment", "Persist an explicit anchor, including one-to-many or missing mappings.",
    ("alignmentId", "eventId", "captureId", "targetEventIds"), alignmentId=S, eventId=I,
    captureId=S, targetEventIds=A, note=S)
add("diff_aligned_events", "Compare matched event outputs; ambiguity requires an explicit candidate choice.",
    ("alignmentId", "eventId", "captureId"), alignmentId=S, eventId=I, captureId=S,
    targetEventId=I, outputIndex=I, threshold=N, relativeThreshold=N, roi=A, channels=A)
add("compare_aligned_constants", "Compare reflected constant values across matched draws, with offsets and unknown semantics preserved.",
    ("alignmentId", "eventId", "stage"), alignmentId=S, eventId=I, stage=S, blockIndex=I)
add("get_artifact", "Read a registered artifact as image, text or resource link.", ("artifactId",), artifactId=S, inline=B)
add("gui_status", "Inspect the optional GUI extension bridge; it does not borrow a live target connection.")
add("gui_select_event", "Ask an enabled GUI extension to open a saved capture and select an event.",
    ("captureId", "eventId"), captureId=S, eventId=I)

# Analysis workflows compose public replay APIs; IDs remain capture-local.
add("locate_draws_at_pixel", "Join pixel history to actions, shader bindings and failure reasons. Returns jobId.",
    ("sessionId", "eventId", "resourceId", "x", "y"), sessionId=S, eventId=I, resourceId=S,
    x=I, y=I, mip=I, slice=I, sample=I, typeCast=S, includePreviews=B, limit=I)
add("visualize_draw_contribution", "Numeric before/after mask, overlay, bounding box and crop for a chosen draw output. Returns jobId.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, resourceIds=A, mip=I, slice=I, sample=I,
    threshold=N, relativeThreshold=N, roi=A, channels=A)
add("preview_resources", "Paged texture contact sheet with resource IDs, dimensions, channels and usages. Returns jobId.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, resourceIds=A, query=S, offset=I, limit=I,
    mip=I, slice=I, sample=I, channels=A, blackPoint={"type": "number"}, whitePoint={"type": "number"}, tileSize=I)
add("trace_output_dependencies", "Backward resource/event graph through API-recorded reads and writes; not pixel-level causality. Returns jobId.",
    ("sessionId", "eventId", "resourceId"), sessionId=S, eventId=I, resourceId=S, maxDepth=I, offset=I, limit=I)
add("group_related_draws", "Rank related geometry across depth, shadow and color draws with explicit evidence. Returns jobId.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, minScore=N, includeConstants=B, includeGeometryHashes=B)
add("list_gpu_counters", "List actual replay-backend GPU counters, units and result types.", ("sessionId",), sessionId=S)
add("profile_events", "Fetch GPU counters, rank events and aggregate marker passes. Replay measurements, not live game timings. Returns jobId.",
    ("sessionId",), sessionId=S, counterIds=A, eventIds=A, limit=I)
add("match_resources", "Rank cross-capture resources by content, layout and shader/binding usage; IDs are never compared as identities. Returns jobId.",
    ("leftSessionId", "leftEventId", "rightSessionId", "rightEventId"), leftSessionId=S, leftEventId=I,
    rightSessionId=S, rightEventId=I, resourceIds=A, kind=S, includeContentHashes=B, offset=I, limit=I, candidateCount=I)
add("track_constant_changes", "Track aligned typed constants across a capture set, export JSON/CSV and charts. Returns jobId.",
    ("alignmentId", "eventId", "stage"), alignmentId=S, eventId=I, stage=S, blockIndex=I, query=S, limit=I)
add("summarize_capture_changes", "Separate matched draw/state/value/output changes from unmatched candidates. Returns jobId.",
    ("leftSessionId", "rightSessionId"), leftSessionId=S, rightSessionId=S, minEventId=I, maxEventId=I,
    includeConstants=B, includeOutputDiffs=B, limit=I)
add("get_event_api_calls", "Structured API calls and typed parameters around an action, including non-action events; paged and searchable.",
    ("sessionId", "eventId"), sessionId=S, eventId=I, before=I, after=I, query=S, offset=I, limit=I, maxDepth=I, arrayLimit=I)
add("query_shader_trace", "Query a saved debug trace by variable, step, instruction or event flag; return changes or last write.",
    ("artifactId",), artifactId=S, variable=S, query=S, mode=S, minStep=I, maxStep=I, instruction=I, flags=S, offset=I, limit=I)
add("annotate_capture", "Persist a note/tag on a capture, event, resource or constant offset; annotationId updates an existing note.",
    ("captureId", "note"), captureId=S, note=S, annotationId=S, eventId=I, resourceId=S, stage=S, blockIndex=I, byteOffset=I, tags=A)
add("list_annotations", "Read persistent analysis notes with capture/event/resource/tag filters.", captureId=S, eventId=I, resourceId=S, tag=S)
add("export_analysis_bundle", "Export capture notes, selected evidence and registered artifacts as Markdown/JSON/ZIP; RDC inclusion is optional. Returns jobId.",
    ("captureId",), captureId=S, eventIds=A, artifactIds=A, includeRdc=B, includeConstants=B, title=S)
add("batch_query", "Run ordered read queries through worker serial queues; project fields with dot paths and retain per-item errors. Returns jobId.",
    ("queries",), queries=A)


def validate(name, args):
    from . import ToolError
    if name not in TOOLS:
        raise ToolError("unknown_tool", name)
    schema = TOOLS[name]["inputSchema"]
    if not isinstance(args, dict):
        raise ToolError("invalid_arguments", "arguments must be an object")
    for key in schema["required"]:
        if key not in args:
            raise ToolError("invalid_arguments", "Missing " + key)
    for key, value in args.items():
        if key not in schema["properties"]:
            raise ToolError("invalid_arguments", "Unknown argument " + key)
        rule = schema["properties"][key]
        types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                 "array": list, "object": dict}
        if not isinstance(value, types[rule["type"]]) or (rule["type"] in ("integer", "number") and isinstance(value, bool)):
            raise ToolError("invalid_arguments", "Invalid type for " + key)
        if "minimum" in rule and value < rule["minimum"]:
            raise ToolError("invalid_arguments", "Invalid range for " + key)
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            raise ToolError("invalid_arguments", "Invalid range for " + key)
