"""Bounded Python 3.6-compatible trace recording; one native batch is atomic."""
import json
import time


def record_trace(controller, trace, variable, plain, flags, event_type, metadata, args):
    payload = {"schemaVersion": 2, "metadata": metadata, "initial": {}, "steps": [],
               "completion": {"status": "truncated", "reason": "initial_budget"}}
    max_steps = args.get("maxSteps", 16384)
    max_bytes = args.get("maxBytes", 32 * 1024 * 1024)
    seconds = args.get("maxSeconds", 30)
    for section in ("inputs", "constantBlocks"):
        payload["initial"][section] = [variable(v) for v in getattr(trace, section, [])]
    used = len(json.dumps(payload).encode("utf-8"))
    started = time.monotonic()
    if used + 1024 > max_bytes:
        payload["initial"] = {}
        return payload
    while True:
        if len(payload["steps"]) >= max_steps or time.monotonic() - started >= seconds:
            payload["completion"] = {"status": "truncated", "reason": "step_budget" if len(payload["steps"]) >= max_steps else "time_budget"}
            break
        batch = controller.ContinueDebug(trace.debugger)
        if not batch:
            payload["completion"] = {"status": "complete", "reason": "debugger_end"}
            break
        exhausted = False
        for state in batch:
            item = {"stepIndex": int(state.stepIndex), "nextInstruction": int(state.nextInstruction),
                    "callstack": plain(state.callstack), "flags": flags(state.flags, event_type),
                    "changes": [{"before": variable(c.before), "after": variable(c.after)} for c in state.changes]}
            size = len(json.dumps(item).encode("utf-8")) + 2
            if len(payload["steps"]) >= max_steps or used + size + 1024 > max_bytes:
                payload["completion"] = {"status": "truncated", "reason": "step_budget" if len(payload["steps"]) >= max_steps else "byte_budget"}
                exhausted = True
                break
            payload["steps"].append(item)
            used += size
        if exhausted:
            break
    payload["completion"]["elapsedSeconds"] = time.monotonic() - started
    payload["completion"]["budgetBoundary"] = "Between ContinueDebug batches; an in-flight native call cannot be forcibly interrupted"
    return payload
