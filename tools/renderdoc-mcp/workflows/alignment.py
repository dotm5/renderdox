import difflib


def pass_key(action):
    return "/".join(x["name"] for x in action["ancestry"])


def score(left, right):
    reasons, total = [], 0.0
    features = [("shaders", 0.42), ("indexHash", 0.17), ("outputDescriptions", 0.10),
                ("topology", 0.06), ("numIndices", 0.07), ("numInstances", 0.03), ("textureHashes", 0.07)]
    for field, weight in features:
        a, b = left.get(field), right.get(field)
        if a not in (None, [], {}) and a == b:
            total += weight
            reasons.append(field + " matched")
    similarity = difflib.SequenceMatcher(None, pass_key(left), pass_key(right)).ratio()
    total += 0.08 * similarity
    reasons.append("pass marker similarity %.3f" % similarity)
    return total, reasons


def align(reference, target):
    mappings = {}
    # Pass matches are established first. Draws search within the most similar
    # pass, with a global fallback when marker hierarchies are absent/changed.
    passes = {}
    for action in target:
        passes.setdefault(pass_key(action), []).append(action)
    pass_matches = {}
    for key in {pass_key(x) for x in reference}:
        ranked = sorted(((difflib.SequenceMatcher(None, key, p).ratio(), p) for p in passes), reverse=True)
        pass_matches[key] = ranked[:3]
    for action in reference:
        ranked_passes = pass_matches[pass_key(action)]
        best = ranked_passes[0][0] if ranked_passes else 0
        pool = [draw for similarity, p in ranked_passes if similarity >= best - 0.08 for draw in passes[p]] if best >= 0.5 else target
        candidates = []
        for draw in pool:
            value, reasons = score(action, draw)
            if value >= 0.35:
                candidates.append({"eventId": draw["eventId"], "score": round(value, 5), "reasons": reasons,
                                   "name": draw["name"], "pass": pass_key(draw)})
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[:5]
        clear = bool(candidates) and candidates[0]["score"] >= 0.65 and (len(candidates) == 1 or candidates[0]["score"] - candidates[1]["score"] >= 0.07)
        mappings[str(action["eventId"])] = {"status": "matched" if clear else "ambiguous" if candidates else "missing",
            "targetEventIds": [candidates[0]["eventId"]] if clear else [], "candidates": candidates, "manual": False}
    # A candidate reused by several reference draws is explicitly many-to-one.
    inverse = {}
    for event, match in mappings.items():
        for target_event in match["targetEventIds"]:
            inverse.setdefault(target_event, []).append(int(event))
    for match in mappings.values():
        if match["targetEventIds"] and len(inverse[match["targetEventIds"][0]]) > 1:
            match["relation"] = "many-to-one"
            match["referenceEventIds"] = inverse[match["targetEventIds"][0]]
        else:
            match["relation"] = "one-to-one" if match["status"] == "matched" else match["status"]
    return {"events": mappings, "passCandidates": pass_matches}
