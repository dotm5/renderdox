"""Compare recorded states without holding native debugger handles.

Alignment stops at the first control-flow mismatch. nextInstruction denotes the
instruction *after* the recorded state, not the instruction that wrote a value.
"""
import math

from contracts import ToolError


def flatten(variables, prefix=""):
    result = {}
    for value in variables:
        name = prefix + str(value.get("name", ""))
        if not name:
            continue
        if value.get("members"):
            result.update(flatten(value["members"], name + "/"))
        else:
            result[name] = value
    return result


def equal(left, right, absolute, relative):
    if left is None or right is None:
        return left is right
    if any(left.get(k) != right.get(k) for k in ("type", "rows", "columns")):
        return False
    if "values" not in left or "values" not in right:
        return None  # resource union views are not numeric identities
    a, b = left["values"], right["values"]
    if len(a) != len(b):
        return False
    floating = left.get("type") in ("Float", "Double", "Half")
    for x, y in zip(a, b):
        if floating:
            # Non-finite values are serialized as strings by the worker.
            if isinstance(x, str) or isinstance(y, str):
                if x != y:
                    return False
            elif not math.isclose(x, y, abs_tol=absolute, rel_tol=relative):
                return False
        elif x != y:
            return False
    return True


def compare_traces(left, right, args):
    for trace in (left, right):
        if trace.get("schemaVersion") != 2 or not isinstance(trace.get("steps"), list):
            raise ToolError("invalid_trace", "Use a schemaVersion 2 debug_shader artifact")
    lm, rm = left["metadata"], right["metadata"]
    if lm.get("replacementState") or rm.get("replacementState"):
        raise ToolError("replacement_active", "Restore replacements before comparison; pipeline bytecode identity is not proven for replaced shaders")
    if lm.get("stage") != "Pixel" or rm.get("stage") != "Pixel":
        raise ToolError("unsupported_stage", "First release compares Pixel traces")
    if not lm.get("shaderSHA256") or lm["shaderSHA256"] != rm.get("shaderSHA256"):
        raise ToolError("shader_mismatch", "Trace comparison requires identical effective shader bytecode")
    absolute, relative = args.get("absoluteThreshold", 0), args.get("relativeThreshold", 0)
    running = [{}, {}]
    for state, trace in zip(running, (left, right)):
        for section in ("inputs", "constantBlocks"):
            state.update(flatten(trace.get("initial", {}).get(section, []), section + "/"))
    unknown = set()
    first = None
    def differences(index, instruction):
        nonlocal first
        changed = []
        for key in sorted(set(running[0]) | set(running[1])):
            a, b = running[0].get(key), running[1].get(key)
            if a is None or b is None:
                unknown.add(key)
                continue
            match = equal(a, b, absolute, relative)
            if match is None:
                unknown.add(key)
            elif not match:
                changed.append({"variable": key, "left": a, "right": b})
        if changed and first is None:
            first = {"stateIndex": index, "nextInstruction": instruction, "variables": changed[:32],
                     "variableCount": len(changed), "phase": "initial" if index < 0 else "state"}
    differences(-1, None)
    occurrences = [{}, {}]
    control = None
    compared = 0
    for index, (a, b) in enumerate(zip(left["steps"], right["steps"])):
        keys = []
        for side, step in enumerate((a, b)):
            key = (step.get("nextInstruction"), tuple(step.get("callstack", [])))
            count = occurrences[side].get(key, 0) + 1
            occurrences[side][key] = count
            keys.append((key, count))
        if keys[0] != keys[1]:
            control = {"stateIndex": index, "leftNextInstruction": a.get("nextInstruction"),
                       "rightNextInstruction": b.get("nextInstruction"), "leftCallstack": a.get("callstack"),
                       "rightCallstack": b.get("callstack"), "reason": "instruction/callstack/occurrence mismatch"}
            break
        for side, step in enumerate((a, b)):
            for change in step.get("changes", []):
                before, after = change.get("before", {}), change.get("after", {})
                # A removed variable is not a persistent live register.
                if before.get("name") and not after.get("name"):
                    for key in flatten([before]):
                        running[side].pop(key, None)
                running[side].update(flatten([after]))
        differences(index, a.get("nextInstruction"))
        compared += 1
    complete = all(t.get("completion", {}).get("status") == "complete" for t in (left, right))
    if complete and control is None and len(left["steps"]) != len(right["steps"]):
        control = {"stateIndex": compared, "reason": "different completed execution lengths"}
    status = "different" if first or control else "incomplete" if not complete or unknown else "equal_in_recorded_scope"
    return {"schemaVersion": 1, "status": status, "left": lm, "right": rm,
            "leftCompletion": left["completion"], "rightCompletion": right["completion"],
            "comparedStates": compared, "firstValueDivergence": first, "firstControlDivergence": control,
            "unknownVariables": sorted(unknown), "absoluteThreshold": absolute, "relativeThreshold": relative,
            "interpretation": "Inputs/constants and observed mutable values only. Stops at control-flow mismatch; no dependency or texture operand inference. nextInstruction follows each recorded state. NaN matches NaN; infinity must match sign."}
