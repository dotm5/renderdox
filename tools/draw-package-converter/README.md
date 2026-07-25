# Draw Package Converter

This external utility validates Draw Evidence GLB files and optionally invokes
an explicitly supplied Blender installation to convert a GLB to FBX.
RenderDoc, qrenderdoc, and the Draw Evidence exporter do not link Blender or
the Autodesk FBX SDK.

```powershell
python .\draw-package-converter.py validate D:\evidence\frame_or_draw_capture_211

python .\draw-package-converter.py fbx `
  --blender 'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe' `
  --input D:\evidence\frame_or_draw_capture_211\geometry\post_vs.glb `
  --output D:\evidence\post_vs.fbx
```

Conversion uses Blender background mode, factory startup, and disabled
auto-execution. Existing FBX files are never overwritten. The destination is
published only after Blender exits successfully.
