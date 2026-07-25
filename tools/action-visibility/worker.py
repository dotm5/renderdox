"""Replay-side Action Visibility validation for an owned RDC capture."""

import hashlib
import json
import os
import time
import traceback

import renderdoc as rd


SCHEMA_VERSION = 1


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def atomic_json(path, value):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def flatten(actions):
    result = []

    def visit(action):
        result.append(action)
        for child in action.children:
            visit(child)

    for root in actions:
        visit(root)
    return result


def flag_set(action, flag):
    return bool(action.flags & flag)


def is_eligible(action):
    if hasattr(action, "IsActionVisibilityEligible"):
        return bool(action.IsActionVisibilityEligible())

    unsupported = (
        rd.ActionFlags.Indirect
        | rd.ActionFlags.MultiAction
        | rd.ActionFlags.Auto
        | rd.ActionFlags.MeshDispatch
        | rd.ActionFlags.DispatchRay
    )
    direct = rd.ActionFlags.Drawcall | rd.ActionFlags.Dispatch
    return not action.children and flag_set(action, direct) and not flag_set(action, unsupported)


def resource_is_null(resource_id):
    return resource_id == rd.ResourceId.Null()


def action_name(action, structured):
    try:
        return action.GetName(structured)
    except BaseException:
        return "EID {}".format(action.eventId)


def append_target(result, seen, resource_id, kind, offset=0, size=1024 * 1024):
    if resource_is_null(resource_id):
        return
    key = str(resource_id)
    if key in seen:
        return
    seen.add(key)
    result.append(
        {
            "kind": kind,
            "resource": resource_id,
            "offset": max(0, int(offset)),
            "size": max(1, min(int(size), 1024 * 1024)),
        }
    )


def observable_targets(action, controller):
    result = []
    seen = set()
    texture_ids = {str(texture.resourceId) for texture in controller.GetTextures()}
    buffer_lengths = {
        str(buffer.resourceId): int(buffer.length) for buffer in controller.GetBuffers()
    }

    for resource_id in action.outputs:
        append_target(result, seen, resource_id, "texture")

    append_target(result, seen, action.depthOut, "texture")
    if str(action.copyDestination) in texture_ids:
        append_target(result, seen, action.copyDestination, "texture")
    elif str(action.copyDestination) in buffer_lengths:
        append_target(
            result,
            seen,
            action.copyDestination,
            "buffer",
            0,
            buffer_lengths[str(action.copyDestination)],
        )

    controller.SetFrameEvent(action.eventId, True)
    pipeline = controller.GetPipelineState()
    for bound in pipeline.GetOutputTargets():
        append_target(result, seen, bound.resource, "texture")
    append_target(result, seen, pipeline.GetDepthTarget().resource, "texture")

    for stage in (
        rd.ShaderStage.Vertex,
        rd.ShaderStage.Hull,
        rd.ShaderStage.Domain,
        rd.ShaderStage.Geometry,
        rd.ShaderStage.Pixel,
        rd.ShaderStage.Compute,
    ):
        try:
            resources = pipeline.GetReadWriteResources(stage)
        except BaseException:
            resources = []
        for bound in resources:
            descriptor = bound.descriptor
            resource_id = descriptor.resource
            if resource_is_null(resource_id):
                continue
            byte_size = int(descriptor.byteSize)
            if byte_size <= 0:
                byte_size = buffer_lengths.get(str(resource_id), 1024 * 1024)
            kind = "texture" if str(resource_id) in texture_ids else "buffer"
            append_target(
                result,
                seen,
                resource_id,
                kind,
                int(descriptor.byteOffset),
                byte_size,
            )

    return result


def candidate_actions(actions, controller):
    eligible = [action for action in actions if is_eligible(action)]
    draws = [
        action
        for action in eligible
        if flag_set(action, rd.ActionFlags.Drawcall)
        and int(action.numIndices) > 0
    ]
    dispatches = [
        action
        for action in eligible
        if flag_set(action, rd.ActionFlags.Dispatch)
        and all(int(value) > 0 for value in action.dispatchDimension)
    ]

    result = []
    for action in list(reversed(draws)) + list(reversed(dispatches)):
        target = observable_targets(action, controller)
        if target:
            result.append((action, target))
    return result


def snapshot(controller, targets, path_prefix):
    resources = []
    combined = hashlib.sha256()
    for index, target in enumerate(targets):
        resource_key = str(target["resource"])
        if target["kind"] == "texture":
            path = "{}-{:02d}.dds".format(path_prefix, index)
            save = rd.TextureSave()
            save.resourceId = target["resource"]
            save.destType = rd.FileType.DDS
            save.mip = 0
            save.slice.sliceIndex = 0
            if not controller.SaveTexture(save, path):
                raise RuntimeError("SaveTexture failed for {}".format(path))
            size = os.path.getsize(path)
            digest = sha256_file(path)
        else:
            data = controller.GetBufferData(
                target["resource"], target["offset"], target["size"]
            )
            path = "{}-{:02d}.bin".format(path_prefix, index)
            with open(path, "wb") as stream:
                stream.write(data)
            size = len(data)
            digest = hashlib.sha256(data).hexdigest().upper()

        combined.update(resource_key.encode("utf-8"))
        combined.update(b":")
        combined.update(digest.encode("ascii"))
        combined.update(b"\n")
        resources.append(
            {
                "kind": target["kind"],
                "resourceId": resource_key,
                "path": path,
                "bytes": size,
                "sha256": digest,
            }
        )
    return {"sha256": combined.hexdigest().upper(), "resources": resources}


def rejected_candidates(actions):
    result = []
    for action in actions:
        if action.eventId <= 0 or is_eligible(action):
            continue
        if (
            action.children
            or flag_set(action, rd.ActionFlags.Indirect)
            or flag_set(action, rd.ActionFlags.MultiAction)
            or flag_set(action, rd.ActionFlags.Auto)
            or flag_set(action, rd.ActionFlags.MeshDispatch)
            or flag_set(action, rd.ActionFlags.DispatchRay)
        ):
            result.append(int(action.eventId))
    return result[:8]


def rejection_only_result(controller, actions, capture_path, before_hash, final_event):
    rejected = rejected_candidates(actions)
    if not rejected:
        raise RuntimeError("No eligible observable action or rejected indirect/multi-action")
    requested = rejected + [0xFFFFFFFE]
    accepted = [int(value) for value in controller.SetDisabledActions(requested)]
    if accepted:
        raise RuntimeError(
            "Indirect/multi-action rejection accepted {} for {}".format(accepted, requested)
        )
    controller.SetFrameEvent(final_event, True)
    after_hash = sha256_file(capture_path)
    if before_hash != after_hash:
        raise RuntimeError("The source RDC changed during rejection-only replay")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "action-visibility-replay-test",
        "status": "passed",
        "mode": "rejection-only",
        "capturePath": os.path.abspath(capture_path),
        "captureSHA256Before": before_hash,
        "captureSHA256After": after_hash,
        "captureUnchanged": True,
        "actionCount": len(actions),
        "eligibleActionCount": sum(1 for candidate in actions if is_eligible(candidate)),
        "requestedDisabledEventIds": requested,
        "acceptedDisabledEventIds": accepted,
        "rejectedCandidateEventIds": rejected,
        "debugMessages": debug_messages(controller),
    }


def debug_messages(controller):
    result = []
    for message in controller.GetDebugMessages():
        result.append(
            {
                "eventId": int(message.eventId),
                "category": str(message.category),
                "severity": str(message.severity),
                "source": str(message.source),
                "description": message.description,
            }
        )
    return result


def analyse(capture_path, output_directory):
    before_hash = sha256_file(capture_path)
    capture = rd.OpenCaptureFile()
    controller = None

    open_result = capture.OpenFile(capture_path, "", None)
    if open_result != rd.ResultCode.Succeeded:
        raise RuntimeError("OpenFile failed: {}".format(open_result))
    if not capture.LocalReplaySupport():
        raise RuntimeError("Capture does not support local replay")

    replay_result, controller = capture.OpenCapture(rd.ReplayOptions(), None)
    if replay_result != rd.ResultCode.Succeeded:
        raise RuntimeError("OpenCapture failed: {}".format(replay_result))

    try:
        structured = controller.GetStructuredFile()
        actions = flatten(controller.GetRootActions())
        if not actions:
            raise RuntimeError("Capture contains no actions")

        candidates = candidate_actions(actions, controller)
        final_event = max(int(candidate.eventId) for candidate in actions)
        if not candidates:
            return rejection_only_result(
                controller, actions, capture_path, before_hash, final_event
            )

        rejected = rejected_candidates(actions)
        invalid_id = 0xFFFFFFFE

        attempts = []
        selected = None
        for attempt_index, candidate in enumerate(candidates):
            action, targets = candidate
            prefix = os.path.join(
                output_directory, "attempt-{:02d}-eid-{}".format(attempt_index, action.eventId)
            )
            clear_result = [int(value) for value in controller.SetDisabledActions([])]
            if clear_result:
                raise RuntimeError("Clearing the disabled set returned unexpected accepted IDs")

            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            baseline = snapshot(controller, targets, prefix + "-baseline")
            baseline_seconds = time.perf_counter() - started

            requested = [int(action.eventId), int(action.eventId), invalid_id] + rejected
            accepted = [int(value) for value in controller.SetDisabledActions(requested)]
            if accepted != [int(action.eventId)]:
                raise RuntimeError(
                    "Eligibility filter accepted {} for requested {}".format(
                        accepted, requested
                    )
                )

            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            disabled = snapshot(controller, targets, prefix + "-disabled")
            disabled_seconds = time.perf_counter() - started

            accepted_after_clear = [int(value) for value in controller.SetDisabledActions([])]
            if accepted_after_clear:
                raise RuntimeError("Clearing the disabled set did not return an empty set")

            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            restored = snapshot(controller, targets, prefix + "-restored")
            restored_seconds = time.perf_counter() - started

            output_changed = baseline["sha256"] != disabled["sha256"]
            output_restored = baseline["sha256"] == restored["sha256"]
            attempts.append(
                {
                    "eventId": int(action.eventId),
                    "name": action_name(action, structured),
                    "outputChanged": output_changed,
                    "outputRestoredExactly": output_restored,
                }
            )
            if output_changed and output_restored:
                selected = {
                    "action": action,
                    "targets": targets,
                    "requested": requested,
                    "accepted": accepted,
                    "baseline": baseline,
                    "disabled": disabled,
                    "restored": restored,
                    "baselineSeconds": baseline_seconds,
                    "disabledSeconds": disabled_seconds,
                    "restoredSeconds": restored_seconds,
                }
                break

        if selected is None and len(candidates) > 1:
            batch_actions = [candidate[0] for candidate in candidates]
            batch_targets = []
            seen_targets = set()
            for _, candidate_targets in candidates:
                for target in candidate_targets:
                    key = str(target["resource"])
                    if key not in seen_targets:
                        seen_targets.add(key)
                        batch_targets.append(target)

            prefix = os.path.join(output_directory, "attempt-batch")
            controller.SetDisabledActions([])
            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            baseline = snapshot(controller, batch_targets, prefix + "-baseline")
            baseline_seconds = time.perf_counter() - started

            requested = (
                [int(candidate.eventId) for candidate in batch_actions]
                + [invalid_id]
                + rejected
            )
            accepted = [int(value) for value in controller.SetDisabledActions(requested)]
            expected = sorted(set(int(candidate.eventId) for candidate in batch_actions))
            if accepted != expected:
                raise RuntimeError(
                    "Batch eligibility filter accepted {} instead of {}".format(
                        accepted, expected
                    )
                )

            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            disabled = snapshot(controller, batch_targets, prefix + "-disabled")
            disabled_seconds = time.perf_counter() - started

            controller.SetDisabledActions([])
            started = time.perf_counter()
            controller.SetFrameEvent(final_event, True)
            restored = snapshot(controller, batch_targets, prefix + "-restored")
            restored_seconds = time.perf_counter() - started

            output_changed = baseline["sha256"] != disabled["sha256"]
            output_restored = baseline["sha256"] == restored["sha256"]
            attempts.append(
                {
                    "eventIds": expected,
                    "name": "all eligible observable actions",
                    "outputChanged": output_changed,
                    "outputRestoredExactly": output_restored,
                }
            )
            if output_changed and output_restored:
                selected = {
                    "action": batch_actions[-1],
                    "actions": batch_actions,
                    "targets": batch_targets,
                    "requested": requested,
                    "accepted": accepted,
                    "baseline": baseline,
                    "disabled": disabled,
                    "restored": restored,
                    "baselineSeconds": baseline_seconds,
                    "disabledSeconds": disabled_seconds,
                    "restoredSeconds": restored_seconds,
                }

        if selected is None:
            raise RuntimeError(
                "No eligible action produced a stable observable output change: {}".format(
                    attempts
                )
            )

        action = selected["action"]
        targets = selected["targets"]
        requested = selected["requested"]
        accepted = selected["accepted"]
        baseline = selected["baseline"]
        disabled = selected["disabled"]
        restored = selected["restored"]
        after_hash = sha256_file(capture_path)
        capture_unchanged = before_hash == after_hash
        if not capture_unchanged:
            raise RuntimeError("The source RDC changed during replay")

        properties = controller.GetAPIProperties()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "action-visibility-replay-test",
            "status": "passed",
            "mode": "output-change",
            "capturePath": os.path.abspath(capture_path),
            "captureSHA256Before": before_hash,
            "captureSHA256After": after_hash,
            "captureUnchanged": capture_unchanged,
            "api": str(properties.pipelineType),
            "actionCount": len(actions),
            "eligibleActionCount": sum(1 for candidate in actions if is_eligible(candidate)),
            "selectedAction": {
                "eventId": int(action.eventId),
                "name": action_name(action, structured),
                "flags": str(action.flags),
            },
            "selectedActionEventIds": [
                int(candidate.eventId)
                for candidate in selected.get("actions", [action])
            ],
            "finalEventId": final_event,
            "observables": [
                {
                    "kind": target["kind"],
                    "resourceId": str(target["resource"]),
                }
                for target in targets
            ],
            "requestedDisabledEventIds": requested,
            "acceptedDisabledEventIds": accepted,
            "rejectedCandidateEventIds": rejected,
            "candidateAttempts": attempts,
            "baseline": baseline,
            "disabled": disabled,
            "restored": restored,
            "outputChanged": True,
            "outputRestoredExactly": True,
            "timingsSeconds": {
                "baselineReplayAndReadback": round(selected["baselineSeconds"], 6),
                "disabledReplayAndReadback": round(selected["disabledSeconds"], 6),
                "restoredReplayAndReadback": round(selected["restoredSeconds"], 6),
            },
            "debugMessages": debug_messages(controller),
        }
    finally:
        if controller is not None:
            controller.Shutdown()
        capture.Shutdown()


def main():
    capture_path = os.environ.get("RDX_ACTION_VIS_CAPTURE")
    output_directory = os.environ.get("RDX_ACTION_VIS_OUTPUT")
    result_path = os.environ.get("RDX_ACTION_VIS_RESULT")
    if not capture_path or not output_directory or not result_path:
        raise RuntimeError("Action Visibility worker environment is incomplete")

    os.makedirs(output_directory, exist_ok=True)
    try:
        result = analyse(capture_path, output_directory)
    except BaseException as exception:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "action-visibility-replay-test",
            "status": "failed",
            "capturePath": os.path.abspath(capture_path),
            "exception": {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            },
        }
    atomic_json(result_path, result)


if __name__ == "__main__":
    main()
