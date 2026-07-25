def texture_export_policy(format_name, component_type, is_depth=False):
    upper = str(format_name).upper()
    component = str(component_type).upper()
    if is_depth:
        return {
            "container": "EXR",
            "extension": ".exr",
            "fidelity": "exact",
            "reason": "Depth data is exported without lossy quantisation",
        }
    if any(token in upper for token in ("BC1", "BC2", "BC3", "BC4", "BC5", "BC6", "BC7")):
        return {
            "container": "DDS",
            "extension": ".dds",
            "fidelity": "exact",
            "reason": "Block-compressed payload and mip chain are preserved",
        }
    if any(token in upper for token in ("ASTC", "ETC", "EAC")):
        return {
            "container": "RAW",
            "extension": ".bin",
            "fidelity": "exact",
            "reason": "The public exporter has no KTX2 destination; raw bytes are preserved",
        }
    if "FLOAT" in component or any(token in upper for token in ("R16F", "R32F", "FLOAT")):
        return {
            "container": "EXR",
            "extension": ".exr",
            "fidelity": "exact",
            "reason": "Floating-point channels are preserved",
        }
    return {
        "container": "PNG",
        "extension": ".png",
        "fidelity": "exact",
        "reason": "Integer/UNORM/SRGB texture exported losslessly",
    }
