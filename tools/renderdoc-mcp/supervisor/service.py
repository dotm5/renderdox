import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from contracts import ToolError, VERSION
from contracts.catalog import validate
from supervisor.process import Worker
from workflows.alignment import align
from workflows.diff import compare, image_artifact
from workflows.analysis import AnalysisWorkflows, JOB_TOOLS


def identifier(kind):
    return kind + "-" + uuid.uuid4().hex


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Service(AnalysisWorkflows):
    def __init__(self, package_root, source_root, interpreter, output):
        self.package_root, self.source_root, self.interpreter = Path(package_root), Path(source_root), Path(interpreter)
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        # Separate native sessions also need separate mutable indexes. A second
        # stdio client can use the same default output location without racing
        # the first client's atomic replacements.
        self.output_lock = open(self.output / ".owner.lock", "a+b")
        self.output_lock.write(b"0")
        self.output_lock.flush()
        self.output_lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.output_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.output_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.output_lock.close()
            self.output = self.output / identifier("instance")
            self.output.mkdir(parents=True)
            self.output_lock = open(self.output / ".owner.lock", "a+b")
            self.output_lock.write(b"0")
            self.output_lock.flush()
            self.output_lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(self.output_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.output_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db_path = self.output / "index.json"
        self.db = json.loads(self.db_path.read_text(encoding="utf-8")) if self.db_path.exists() else {}
        for name in ("captures", "sets", "alignments", "artifacts", "jobs", "annotations"):
            self.db.setdefault(name, {})
        for job in self.db["jobs"].values():
            if job["status"] in ("queued", "running", "stop_requested"):
                job.update(status="failed", error={"code": "service_restarted", "message": "Previous service ended before the job completed"})
        self.sessions, self.connections, self.targets = {}, {}, {}
        self.tasks, self.stops, self.workers = {}, {}, set()
        self.capture_open_lock = asyncio.Lock()
        self.save()

    def save(self):
        temporary = self.db_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.db, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, self.db_path)

    def register(self, value, provenance=None):
        if isinstance(value, dict):
            if "artifactId" in value and "path" in value:
                self.db["artifacts"][value["artifactId"]] = dict(value, provenance=provenance)
            for item in list(value.values()):
                self.register(item, provenance)
        elif isinstance(value, list):
            for item in value:
                self.register(item, provenance)
        return value

    def get(self, values, key, kind):
        if key not in values:
            raise ToolError("missing_" + kind, str(key))
        return values[key]

    async def worker(self, mode, on_event=None):
        instance = Worker(self.package_root, self.source_root, self.interpreter, self.output, mode, on_event)
        await instance.start()
        self.workers.add(instance)
        return instance

    def job(self, kind, run):
        key = identifier("job")
        stop = asyncio.Event()
        info = {"jobId": key, "type": kind, "status": "queued", "createdAt": time.time(), "progress": 0}
        self.db["jobs"][key], self.stops[key] = info, stop
        async def execute():
            try:
                if stop.is_set():
                    info.update(status="cancelled", completedAt=time.time())
                    return
                info.update(status="running", startedAt=time.time())
                self.save()
                result = await run(info, stop)
                info.update(status="cancelled" if stop.is_set() else "completed", result=self.register(result),
                            completedAt=time.time(), progress=1)
            except Exception as exc:
                info.update(status="failed", completedAt=time.time(),
                            error=exc.payload() if isinstance(exc, ToolError) else {"code": type(exc).__name__, "message": str(exc)})
            finally:
                self.save()
        self.tasks[key] = asyncio.create_task(execute())
        self.save()
        return {"jobId": key, "status": info["status"]}

    async def add_capture(self, path, **metadata):
        path = str(Path(path).resolve())
        if not Path(path).is_file():
            raise ToolError("missing_file", path)
        digest = await asyncio.to_thread(sha256, path)
        # Identity includes bytes; paths remain available even for repeated files.
        key = "capture-" + digest
        old = self.db["captures"].get(key, {})
        value = dict(old, captureId=key, path=path, sha256=digest, byteLength=Path(path).stat().st_size,
                     collectedAt=time.time(), state="ready", **metadata)
        self.db["captures"][key] = value
        self.save()
        return value

    async def open_path(self, path=None, capture_id=None):
        if capture_id:
            capture = self.get(self.db["captures"], capture_id, "capture")
        elif path:
            capture = await self.add_capture(path, source="file")
        else:
            raise ToolError("invalid_arguments", "path or captureId is required")
        worker = await self.worker("replay")
        try:
            summary = await worker.call("open_capture", {"path": capture["path"]})
        except BaseException:
            await worker.close()
            self.workers.discard(worker)
            raise
        key = identifier("session")
        self.sessions[key] = {"sessionId": key, "captureId": capture["captureId"], "generation": uuid.uuid4().hex,
                              "worker": worker, "state": "ready", "summary": summary}
        self.register(summary, {"captureId": capture["captureId"]})
        self.save()
        return {"sessionId": key, "captureId": capture["captureId"], "generation": self.sessions[key]["generation"], "summary": summary}

    async def session_for(self, capture_id):
        async with self.capture_open_lock:
            for key, session in self.sessions.items():
                if session["captureId"] == capture_id and session["state"] == "ready":
                    return key, False
            result = await self.open_path(capture_id=capture_id)
            return result["sessionId"], True

    async def close_session(self, key):
        session = self.get(self.sessions, key, "session")
        session["state"] = "closing"
        await session["worker"].close()
        self.workers.discard(session["worker"])
        del self.sessions[key]
        return {"closed": True, "sessionId": key}

    async def query(self, name, args):
        session = self.get(self.sessions, args["sessionId"], "session")
        if session["state"] != "ready":
            raise ToolError("session_closing", args["sessionId"])
        params = {k: v for k, v in args.items() if k != "sessionId"}
        result = await session["worker"].call(name, params)
        self.register(result, {"captureId": session["captureId"], "eventId": args.get("eventId"), "resourceId": args.get("resourceId")})
        if isinstance(result, dict):
            result = dict(result, captureId=session["captureId"], sessionId=args["sessionId"])
        self.save()
        return result

    async def discover(self, args):
        worker = await self.worker("target")
        try:
            result = await worker.call("list_targets", args)
            for target in result["targets"]:
                # Stable for this discovery generation; not a bare recycled port.
                key = identifier("target")
                target.update(targetId=key, discoveredAt=time.time(), generation=uuid.uuid4().hex)
                self.targets[key] = target
            return result
        finally:
            await worker.close()
            self.workers.discard(worker)

    async def connect(self, args):
        target = self.get(self.targets, args["targetId"], "target")
        key = identifier("connection")
        record = {"connectionId": key, "targetId": args["targetId"], "captures": {}, "messages": [],
                  "captureGate": asyncio.Lock(), "changed": asyncio.Event(), "connected": False}
        def on_event(event):
            record["messages"].append(event)
            record["messages"] = record["messages"][-100:]
            if event["type"] == "NewCapture":
                record["captures"][str(event["capture"]["remoteCaptureId"])] = dict(event["capture"], receivedAt=event["receivedUnix"])
                self.register(event["capture"], {"connectionId": key})
            elif event["type"] == "CaptureCopied":
                capture = record["captures"].get(str(event["capture"]["remoteCaptureId"]))
                if capture:
                    capture["copiedPath"] = event["capture"]["path"]
            elif event["type"] == "Disconnected":
                record["connected"] = False
            elif event["type"] == "CaptureProgress":
                record["captureProgress"] = event["progress"]
            record["changed"].set()
        worker = await self.worker("target", on_event)
        try:
            result = await worker.call("connect_target", dict(target, **{k: v for k, v in args.items() if k != "targetId"}))
            record.update(result, worker=worker)
            self.connections[key] = record
            return {k: v for k, v in record.items() if k not in ("worker", "captureGate", "changed")}
        except BaseException:
            await worker.close()
            self.workers.discard(worker)
            raise

    async def connection_query(self, name, args):
        record = self.get(self.connections, args["connectionId"], "connection")
        if name == "disconnect_target":
            # Wait for the active capture round to finish; its stop flag can be
            # set through stop_job before disconnecting.
            async with record["captureGate"]:
                await record["worker"].close()
                self.workers.discard(record["worker"])
                record["connected"] = False
            return {"disconnected": True}
        result = await record["worker"].call(name, {})
        record.update(result)
        return {k: v for k, v in record.items() if k not in ("worker", "captureGate", "changed")}

    async def wait_change(self, record, stop, deadline):
        if stop.is_set():
            return False
        if time.monotonic() >= deadline:
            raise ToolError("capture_timeout", "Target did not complete capture/copy before completionTimeoutSeconds")
        record["changed"].clear()
        try:
            await asyncio.wait_for(record["changed"].wait(), min(0.25, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            pass
        if not record["connected"]:
            raise ToolError("disconnected", "Target disconnected while capture was pending")
        return True

    async def collect(self, record, remote_id, stop, deadline):
        remote = self.get(record["captures"], str(remote_id), "remote_capture")
        destination = self.output / "captures" / (record["connectionId"] + "-" + str(remote_id) + ".rdc")
        remote.pop("copiedPath", None)
        await record["worker"].call("save_capture", {"remoteCaptureId": remote_id, "path": str(destination)})
        while "copiedPath" not in remote:
            # Collection already started, so a stop only applies after its
            # completion; file existence is not a completion signal.
            await self.wait_change(record, asyncio.Event(), deadline)
        thumbnail = None
        if remote.get("thumbnailRGB") and remote.get("thumbWidth") and remote.get("thumbHeight"):
            def convert_thumbnail():
                import numpy as np
                pixels = np.frombuffer(Path(remote["thumbnailRGB"]["path"]).read_bytes(), dtype=np.uint8).reshape(remote["thumbHeight"], remote["thumbWidth"], 3)
                return image_artifact(self.output / "thumbnails", pixels, "capture-thumbnail")
            thumbnail = await asyncio.to_thread(convert_thumbnail)
            self.register(thumbnail, {"connectionId": record["connectionId"], "remoteCaptureId": remote_id})
        return await self.add_capture(remote["copiedPath"], source="target", connectionId=record["connectionId"],
            remoteCaptureId=remote_id, frameNumber=remote.get("frameNumber"), timestamp=remote.get("timestamp"),
            thumbnail=thumbnail,
            thumbnailRGB=remote.get("thumbnailRGB"), thumbWidth=remote.get("thumbWidth"), thumbHeight=remote.get("thumbHeight"))

    def capture_job(self, name, args):
        record = self.get(self.connections, args["connectionId"], "connection")
        if name == "capture_at_frame" and "frameNumber" not in args:
            raise ToolError("invalid_arguments", "frameNumber is required")
        async def run(info, stop):
            rounds = args.get("count", 1) if name == "capture_sequence" else 1
            frames = args.get("framesPerCapture", 1)
            interval, delay = args.get("intervalSeconds", 1), args.get("delaySeconds", 0)
            timeout = args.get("completionTimeoutSeconds", 120)
            result = {"rounds": [], "captureIds": [], "requestedRounds": 0, "receivedFrames": 0,
                      "rdcCount": 0, "correlation": "candidate-by-time-and-connection; no API request token"}
            if name == "save_capture":
                async with record["captureGate"]:
                    capture = await self.collect(record, args["remoteCaptureId"], stop, time.monotonic() + timeout)
                return {"capture": capture}
            set_id = args.get("captureSetId") or identifier("set")
            if set_id not in self.db["sets"]:
                self.db["sets"][set_id] = {"captureSetId": set_id, "captureIds": [], "name": "Runtime " + record["connectionId"],
                                          "temporal": True, "referenceCaptureId": None}
            result["captureSetId"] = set_id
            started = time.monotonic()
            wall_start = time.time()
            info["partialResult"] = result
            async with record["captureGate"]:
                for index in range(rounds):
                    scheduled = started + delay + index * interval
                    remaining = scheduled - time.monotonic()
                    if remaining > 0:
                        try:
                            await asyncio.wait_for(stop.wait(), remaining)
                        except asyncio.TimeoutError:
                            pass
                    if stop.is_set():
                        break
                    known = set(record["captures"])
                    request_time = time.time()
                    operation = "capture_at_frame" if name == "capture_at_frame" else "capture_now"
                    request = await record["worker"].call(operation, args)
                    result["requestedRounds"] += 1
                    round_info = {"index": index, "plannedAt": wall_start + delay + index * interval,
                                  "requestedAt": request_time, "request": request, "captures": [], "attribution": "candidate"}
                    result["rounds"].append(round_info)
                    deadline = time.monotonic() + timeout
                    candidates = []
                    while len(candidates) < frames:
                        candidates = [v for k, v in record["captures"].items() if k not in known and v.get("timestamp", 0) >= int(request_time)]
                        if len(candidates) >= frames:
                            break
                        # A submitted round is asynchronous in the target. Stop
                        # prevents subsequent rounds, but still collects the
                        # already-submitted frame(s) before releasing the gate.
                        await self.wait_change(record, asyncio.Event(), deadline)
                    # Every newly reported capture is preserved; external
                    # hotkeys may have caused extra frames, so report ambiguity.
                    if len(candidates) != frames:
                        round_info["attribution"] = "ambiguous"
                    for remote in candidates:
                        capture = await self.collect(record, remote["remoteCaptureId"], stop, deadline)
                        result["captureIds"].append(capture["captureId"])
                        result["receivedFrames"] += 1
                        result["rdcCount"] += 1
                        round_info["captures"].append({"captureId": capture["captureId"], "frameNumber": capture.get("frameNumber"),
                                                       "captureReceivedAt": remote["receivedAt"], "thumbnail": capture.get("thumbnail")})
                        collection = self.db["sets"][set_id]
                        if capture["captureId"] not in collection["captureIds"]:
                            collection["captureIds"].append(capture["captureId"])
                        collection["referenceCaptureId"] = collection["referenceCaptureId"] or capture["captureId"]
                    info["progress"] = (index + 1) / rounds
                    self.save()
                    # Delay next round from now when a planned time was missed:
                    # no immediate catch-up burst after a slow capture.
                    if time.monotonic() > scheduled + interval:
                        started = time.monotonic() - delay - index * interval
                        wall_start = time.time() - delay - index * interval
            return result
        return self.job(name, run)

    async def injection(self, name, args):
        worker = await self.worker("target")
        try:
            result = await worker.call(name, args)
        finally:
            await worker.close()
            self.workers.discard(worker)
        target = {"targetId": identifier("target"), "ident": result["ident"], "host": "", "generation": uuid.uuid4().hex}
        self.targets[target["targetId"]] = target
        return {"injection": result, "connection": await self.connect({"targetId": target["targetId"]})}

    async def diff_pair(self, args):
        common = {k: v for k, v in args.items() if k in ("mip", "slice", "sample")}
        left = await self.query("read_texture", dict(common, sessionId=args["leftSessionId"], eventId=args["leftEventId"], resourceId=args["leftResourceId"]))
        right = await self.query("read_texture", dict(common, sessionId=args["rightSessionId"], eventId=args["rightEventId"], resourceId=args["rightResourceId"]))
        result = await asyncio.to_thread(compare, left, right, args, self.output / "diff")
        if args.get("displayImages", True):
            result["leftPreview"] = await self.query("view_texture", dict(common, sessionId=args["leftSessionId"], eventId=args["leftEventId"], resourceId=args["leftResourceId"]))
            result["rightPreview"] = await self.query("view_texture", dict(common, sessionId=args["rightSessionId"], eventId=args["rightEventId"], resourceId=args["rightResourceId"]))
        return self.register(result)

    async def signatures(self, capture_id, args):
        cache = self.output / "signatures" / (capture_id + ("-textures" if args.get("includeTextureHashes") else "") + "-v1.json")
        if cache.exists():
            return json.loads(cache.read_text())
        key, owned = await self.session_for(capture_id)
        try:
            result = await self.query("build_signatures", dict(sessionId=key, includeTextureHashes=args.get("includeTextureHashes", False)))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(result), encoding="utf-8")
            return result
        finally:
            if owned:
                await self.close_session(key)

    def alignment_job(self, args):
        collection = self.get(self.db["sets"], args["captureSetId"], "capture_set")
        reference_id = args.get("referenceCaptureId", collection["referenceCaptureId"])
        if reference_id not in collection["captureIds"]:
            raise ToolError("invalid_reference", str(reference_id))
        async def run(info, stop):
            reference = await self.signatures(reference_id, args)
            result = {"alignmentId": identifier("alignment"), "algorithmVersion": 1,
                      "captureSetId": args["captureSetId"], "referenceCaptureId": reference_id, "captures": {}}
            for i, capture_id in enumerate(collection["captureIds"]):
                if stop.is_set():
                    break
                if capture_id == reference_id:
                    continue
                target = await self.signatures(capture_id, args)
                result["captures"][capture_id] = await asyncio.to_thread(align, reference["signatures"], target["signatures"])
                info["progress"] = (i + 1) / len(collection["captureIds"])
            self.db["alignments"][result["alignmentId"]] = result
            self.save()
            return {"alignmentId": result["alignmentId"], "referenceCaptureId": reference_id,
                    "captureIds": list(result["captures"]), "algorithmVersion": 1}
        return self.job("align_events", run)

    def match(self, alignment_id, event, capture_id, explicit=None):
        alignment = self.get(self.db["alignments"], alignment_id, "alignment")
        target = self.get(alignment["captures"], capture_id, "alignment_capture")
        mapping = self.get(target["events"], str(event), "aligned_event")
        events = mapping["targetEventIds"]
        if explicit is not None:
            return alignment, explicit
        if mapping["status"] not in ("matched", "manual") or len(events) != 1:
            raise ToolError("ambiguous_alignment", "Choose targetEventId or override_alignment", mapping)
        return alignment, events[0]

    async def call(self, name, args):
        validate(name, args)
        if name in JOB_TOOLS:
            return self.analysis_job(name, args)
        if name == "annotate_capture":
            return self.annotate(args)
        if name == "list_annotations":
            return self.annotations(args)
        if name == "query_shader_trace":
            return await self.query_trace(args)
        if name == "get_capabilities":
            if args.get("sessionId"):
                return await self.query(name, args)
            return {"version": VERSION, "packageRoot": str(self.package_root), "interpreter": str(self.interpreter),
                    "interpreterExists": self.interpreter.is_file(), "outputDirectory": str(self.output),
                    "activeSessions": [{k: v for k, v in x.items() if k not in ("worker", "summary")} for x in self.sessions.values()],
                    "sessionCapabilities": "Open an RDC to inspect backend/stage support", "transport": "stdio"}
        if name == "list_targets":
            return await self.discover(args)
        if name == "connect_target":
            return await self.connect(args)
        if name in ("get_connection", "disconnect_target", "cycle_capture_window"):
            return await self.connection_query(name, args)
        if name in ("capture_now", "capture_after", "capture_at_frame", "capture_sequence", "save_capture"):
            return self.capture_job(name, args)
        if name == "list_captures":
            if args.get("connectionId"):
                return {"captures": list(self.get(self.connections, args["connectionId"], "connection")["captures"].values())}
            return {"captures": list(self.db["captures"].values())}
        if name in ("get_job", "stop_job"):
            info = self.get(self.db["jobs"], args["jobId"], "job")
            if name == "stop_job" and info["status"] in ("queued", "running"):
                self.stops[args["jobId"]].set()
                info["status"] = "stop_requested"
                self.save()
            return info
        if name == "open_capture":
            async def run(info, stop):
                result = await self.open_path(args.get("path"), args.get("captureId"))
                if stop.is_set():
                    await self.close_session(result["sessionId"])
                    return {"openedThenClosed": True, "captureId": result["captureId"]}
                return result
            return self.job(name, run)
        if name == "close_capture":
            return await self.close_session(args["sessionId"])
        if name in ("launch_and_capture", "inject_process"):
            return self.job(name, lambda info, stop: self.injection(name, args))
        if name == "diff_event":
            raw = await self.query(name, args)
            raw["comparisons"] = [await asyncio.to_thread(compare, a, b, args, self.output / "diff") for a, b in zip(raw["before"], raw["after"])]
            self.register(raw)
            self.save()
            return raw
        if name == "diff_captures":
            result = await self.diff_pair(args)
            self.save()
            return result
        if name == "create_capture_set":
            captures = args["captureIds"]
            if not captures or any(x not in self.db["captures"] for x in captures):
                raise ToolError("missing_capture", "All captureIds must be collected/opened first")
            reference = args.get("referenceCaptureId", captures[0])
            if reference not in captures:
                raise ToolError("invalid_reference", reference)
            key = identifier("set")
            result = dict(args, captureSetId=key, referenceCaptureId=reference, temporal=args.get("temporal", False))
            self.db["sets"][key] = result
            self.save()
            return result
        if name == "list_capture_sets":
            return {"captureSets": list(self.db["sets"].values())}
        if name == "align_events":
            return self.alignment_job(args)
        if name in ("get_aligned_event", "override_alignment"):
            alignment = self.get(self.db["alignments"], args["alignmentId"], "alignment")
            if name == "get_aligned_event":
                return {"referenceCaptureId": alignment["referenceCaptureId"], "eventId": args["eventId"],
                        "captures": {key: value["events"].get(str(args["eventId"])) for key, value in alignment["captures"].items()
                                     if not args.get("captureId") or args["captureId"] == key}}
            target = self.get(alignment["captures"], args["captureId"], "alignment_capture")
            event = self.get(target["events"], str(args["eventId"]), "aligned_event")
            event.update(status="manual", manual=True, targetEventIds=args["targetEventIds"], note=args.get("note", ""),
                         relation="one-to-many" if len(args["targetEventIds"]) > 1 else "one-to-one" if args["targetEventIds"] else "missing")
            self.save()
            return event
        if name == "diff_aligned_events":
            alignment, target_event = self.match(args["alignmentId"], args["eventId"], args["captureId"], args.get("targetEventId"))
            left_key, left_owned = await self.session_for(alignment["referenceCaptureId"])
            right_key, right_owned = await self.session_for(args["captureId"])
            try:
                left = await self.query("get_pipeline_state", {"sessionId": left_key, "eventId": args["eventId"]})
                right = await self.query("get_pipeline_state", {"sessionId": right_key, "eventId": target_event})
                index = args.get("outputIndex", 0)
                return await self.diff_pair(dict({k: v for k, v in args.items() if k in ("threshold", "relativeThreshold", "roi", "channels")},
                    leftSessionId=left_key, leftEventId=args["eventId"], leftResourceId=left["outputTargets"][index]["resource"],
                    rightSessionId=right_key, rightEventId=target_event, rightResourceId=right["outputTargets"][index]["resource"]))
            finally:
                if left_owned:
                    await self.close_session(left_key)
                if right_owned:
                    await self.close_session(right_key)
                self.save()
        if name == "compare_aligned_constants":
            alignment = self.get(self.db["alignments"], args["alignmentId"], "alignment")
            values, baseline = {}, None
            for capture_id in [alignment["referenceCaptureId"]] + list(alignment["captures"]):
                try:
                    event = args["eventId"] if capture_id == alignment["referenceCaptureId"] else self.match(args["alignmentId"], args["eventId"], capture_id)[1]
                    key, owned = await self.session_for(capture_id)
                    try:
                        request = {"sessionId": key, "eventId": event, "stage": args["stage"]}
                        if "blockIndex" in args:
                            request["blockIndex"] = args["blockIndex"]
                        current = await self.query("get_constants", request)
                        normalized = [{"index": x["index"], "variables": x["variables"]} for x in current["blocks"]]
                        if baseline is None:
                            baseline = normalized
                        changes = constant_changes(baseline, normalized)
                        values[capture_id] = {"eventId": event, "constants": current, "changed": bool(changes), "changes": changes}
                    finally:
                        if owned:
                            await self.close_session(key)
                except ToolError as exc:
                    values[capture_id] = {"error": exc.payload()}
            return {"referenceCaptureId": alignment["referenceCaptureId"], "captures": values,
                    "interpretation": "Reflected/offset values; no inferred material semantics or causality"}
        if name == "get_artifact":
            return self.get(self.db["artifacts"], args["artifactId"], "artifact")
        if name in ("gui_status", "gui_select_event"):
            from gui_bridge.client import send
            request = {"operation": name}
            if name == "gui_select_event":
                request.update(path=self.get(self.db["captures"], args["captureId"], "capture")["path"], eventId=args["eventId"])
            return await asyncio.to_thread(send, request)
        return await self.query(name, args)

    async def close(self):
        for stop in self.stops.values():
            stop.set()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        await asyncio.gather(*(worker.close() for worker in list(self.workers)), return_exceptions=True)
        self.output_lock.close()


def constant_changes(left, right):
    def flatten(blocks):
        result = {}
        def visit(variable, prefix):
            path = prefix + "/" + variable["name"]
            if variable.get("members"):
                for member in variable["members"]:
                    visit(member, path)
            else:
                result[path] = {k: variable.get(k) for k in ("type", "rows", "columns", "byteOffset", "values", "rawValue")}
        for block in blocks:
            for variable in block["variables"]:
                visit(variable, "block" + str(block["index"]))
        return result
    a, b = flatten(left), flatten(right)
    return [{"path": key, "before": a.get(key), "after": b.get(key)} for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)]
