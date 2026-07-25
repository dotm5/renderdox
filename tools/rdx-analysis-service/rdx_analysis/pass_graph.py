from bisect import bisect_left

from .common import structural_hash


READ_USAGES = {
    "VertexBuffer",
    "IndexBuffer",
    "VS_Constants",
    "HS_Constants",
    "DS_Constants",
    "GS_Constants",
    "PS_Constants",
    "CS_Constants",
    "TS_Constants",
    "MS_Constants",
    "All_Constants",
    "VS_Resource",
    "HS_Resource",
    "DS_Resource",
    "GS_Resource",
    "PS_Resource",
    "CS_Resource",
    "TS_Resource",
    "MS_Resource",
    "All_Resource",
    "InputTarget",
    "Indirect",
    "Resolve",
    "ResolveSrc",
    "Copy",
    "CopySrc",
}

WRITE_USAGES = {
    "StreamOut",
    "VS_RWResource",
    "HS_RWResource",
    "DS_RWResource",
    "GS_RWResource",
    "PS_RWResource",
    "CS_RWResource",
    "TS_RWResource",
    "MS_RWResource",
    "All_RWResource",
    "ColorTarget",
    "DepthStencilTarget",
    "Clear",
    "Discard",
    "GenMips",
    "Resolve",
    "ResolveDst",
    "Copy",
    "CopyDst",
    "CPUWrite",
}


def owning_action_eid(sorted_action_eids, usage_eid):
    """Map an API event to the action whose event range contains it."""
    position = bisect_left(sorted_action_eids, usage_eid)
    if position >= len(sorted_action_eids):
        return None
    return sorted_action_eids[position]


def usage_sets(actions, resource_usages):
    action_eids = sorted(action["eventId"] for action in actions)
    by_eid = {
        eid: {"reads": set(), "writes": set(), "usageKinds": {}}
        for eid in action_eids
    }
    for resource in resource_usages:
        resource_identifier = resource["resourceId"]
        for usage in resource.get("usages", []):
            owner = owning_action_eid(action_eids, usage["eventId"])
            if owner is None:
                continue
            kind = usage["usage"]
            if kind in READ_USAGES:
                by_eid[owner]["reads"].add(resource_identifier)
            if kind in WRITE_USAGES:
                by_eid[owner]["writes"].add(resource_identifier)
            by_eid[owner]["usageKinds"].setdefault(resource_identifier, set()).add(kind)
    return by_eid


def dependency_edges(actions, per_action):
    edges = []
    last_writer = {}
    seen = set()
    for action in sorted(actions, key=lambda item: item["eventId"]):
        event_id = action["eventId"]
        usage = per_action[event_id]
        for resource in sorted(usage["reads"]):
            producer = last_writer.get(resource)
            key = (producer, event_id, resource)
            if producer is not None and key not in seen:
                seen.add(key)
                edges.append(
                    {
                        "fromEventId": producer,
                        "toEventId": event_id,
                        "resourceId": resource,
                        "kind": "write-to-read",
                    }
                )
        for resource in sorted(usage["writes"]):
            last_writer[resource] = event_id
    return edges


def build_passes(action_signatures, edges):
    passes = []
    action_to_pass = {}
    current = None
    for action in action_signatures:
        grouping_key = (
            action.get("workClass"),
            tuple(action.get("outputResources", [])),
            tuple(action.get("renderTargetFormats", [])),
        )
        if current is None or current["_groupingKey"] != grouping_key:
            current = {
                "passIndex": len(passes),
                "actionEventIds": [],
                "actionKinds": [],
                "inputResources": set(),
                "outputResources": set(),
                "inputResourceKeys": set(),
                "outputResourceKeys": set(),
                "shaderHashes": set(),
                "pipelineStateHashes": set(),
                "viewports": [],
                "renderTargetFormats": list(action.get("renderTargetFormats", [])),
                "_groupingKey": grouping_key,
            }
            passes.append(current)

        current["actionEventIds"].append(action["eventId"])
        current["actionKinds"].append(action["kind"])
        current["inputResources"].update(action.get("inputResources", []))
        current["outputResources"].update(action.get("outputResources", []))
        current["inputResourceKeys"].update(action.get("inputResourceKeys", []))
        current["outputResourceKeys"].update(action.get("outputResourceKeys", []))
        current["shaderHashes"].update(action.get("shaderHashes", []))
        current["pipelineStateHashes"].add(action["pipelineStateHash"])
        if action.get("viewport") not in current["viewports"]:
            current["viewports"].append(action.get("viewport"))
        action_to_pass[action["eventId"]] = current["passIndex"]

    for item in passes:
        item.pop("_groupingKey")
        item["inputResources"] = sorted(item["inputResources"])
        item["outputResources"] = sorted(item["outputResources"])
        item["inputResourceKeys"] = sorted(item["inputResourceKeys"])
        item["outputResourceKeys"] = sorted(item["outputResourceKeys"])
        item["shaderHashes"] = sorted(item["shaderHashes"])
        item["pipelineStateHashes"] = sorted(item["pipelineStateHashes"])
        canonical = {
            "actionKinds": item["actionKinds"],
            "relativeOrder": list(range(len(item["actionEventIds"]))),
            "inputResourceKeys": item["inputResourceKeys"],
            "outputResourceKeys": item["outputResourceKeys"],
            "shaderHashes": item["shaderHashes"],
            "pipelineStateHashes": item["pipelineStateHashes"],
            "viewports": item["viewports"],
            "renderTargetFormats": item["renderTargetFormats"],
        }
        item["structuralSignature"] = structural_hash(canonical)

    pass_edges = []
    seen = set()
    for edge in edges:
        source = action_to_pass.get(edge["fromEventId"])
        target = action_to_pass.get(edge["toEventId"])
        if source is None or target is None or source == target:
            continue
        key = (source, target, edge["resourceId"])
        if key in seen:
            continue
        seen.add(key)
        pass_edges.append(
            {
                "fromPass": source,
                "toPass": target,
                "resourceId": edge["resourceId"],
                "kind": edge["kind"],
            }
        )

    return passes, pass_edges


def build_pass_graph(actions, resource_usages, action_signatures):
    per_action = usage_sets(actions, resource_usages)
    edges = dependency_edges(actions, per_action)
    passes, pass_edges = build_passes(action_signatures, edges)
    return {
        "actions": [
            {
                "eventId": action["eventId"],
                "reads": sorted(per_action[action["eventId"]]["reads"]),
                "writes": sorted(per_action[action["eventId"]]["writes"]),
                "usageKinds": {
                    resource: sorted(kinds)
                    for resource, kinds in sorted(
                        per_action[action["eventId"]]["usageKinds"].items()
                    )
                },
            }
            for action in actions
        ],
        "actionEdges": edges,
        "passes": passes,
        "passEdges": pass_edges,
    }
