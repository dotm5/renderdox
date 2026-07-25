def build_multiaction_map(actions):
    """Build a deterministic parent-to-leaf-draw map from flattened action records."""
    by_event = {int(action["eventId"]): action for action in actions}

    def descendants(action):
        result = []
        for event_id in action.get("children", []):
            child = by_event.get(int(event_id))
            if child is None:
                continue
            result.append(child)
            result.extend(descendants(child))
        return result

    parents = []
    for action in actions:
        flags = set(action.get("flags", []))
        if not action.get("children") or not flags.intersection(("MultiAction", "Indirect")):
            continue

        nested = descendants(action)
        leaf_draws = [
            child
            for child in nested
            if not child.get("children") and "Drawcall" in child.get("flags", [])
        ]
        if not leaf_draws:
            continue

        children = []
        for child in leaf_draws:
            outputs = sorted(
                set(
                    resource
                    for resource in child.get("outputResources", [])
                    if resource is not None
                )
            )
            depth = child.get("depthOutput")
            if depth is not None:
                outputs = sorted(set(outputs + [depth]))
            children.append(
                {
                    "eventId": int(child["eventId"]),
                    "actionId": int(child.get("actionId", 0)),
                    "drawIndex": int(child.get("drawIndex", 0)),
                    "name": child.get("name", ""),
                    "flags": list(child.get("flags", [])),
                    "numIndices": int(child.get("numIndices", 0)),
                    "numInstances": int(child.get("numInstances", 0)),
                    "outputResources": outputs,
                }
            )

        parents.append(
            {
                "parentEventId": int(action["eventId"]),
                "parentActionId": int(action.get("actionId", 0)),
                "name": action.get("name", ""),
                "flags": list(action.get("flags", [])),
                "effectiveEventId": int(nested[-1]["eventId"]),
                "overlayChildEventIds": [child["eventId"] for child in children],
                "children": children,
            }
        )

    return {
        "parentCount": len(parents),
        "childDrawCount": sum(len(parent["children"]) for parent in parents),
        "parents": parents,
    }


def overlay_events_for_target(parent, resource_id):
    """Mirror ReplayOutput's displayed-target filtering for report/unit-test use."""
    if resource_id is None:
        return list(parent.get("overlayChildEventIds", []))
    return [
        child["eventId"]
        for child in parent.get("children", [])
        if resource_id in child.get("outputResources", [])
    ]
