"""Executed only by an explicitly supplied Blender executable."""

import os
import sys


def main():
    import bpy

    arguments = sys.argv[sys.argv.index("--") + 1 :]
    if len(arguments) != 2:
        raise RuntimeError("Expected source GLB and destination FBX")
    source, destination = map(os.path.abspath, arguments)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=source)
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not import the GLB")
    if not any(item.type == "MESH" for item in bpy.context.scene.objects):
        raise RuntimeError("Imported GLB contains no mesh objects")
    result = bpy.ops.export_scene.fbx(
        filepath=destination,
        use_selection=False,
        path_mode="AUTO",
        bake_anim=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError("Blender did not export the FBX")


if __name__ == "__main__":
    main()
