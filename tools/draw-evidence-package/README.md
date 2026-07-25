# Draw Evidence Package

This tool exports evidence for one existing RenderDoc Draw/Dispatch action.
It launches the matching qrenderdoc executable as a dedicated embedded-Python
worker, opens the RDC read-only, writes into a staging directory, and
atomically publishes the completed package.

```powershell
python .\draw-evidence.py `
  --qrenderdoc ..\..\x64\Development\qrendertest.exe `
  --capture D:\captures\frame.rdc `
  --event 211 `
  --output D:\evidence
```

Use `--instance`, `--max-resource-mib`, and `--timeout-seconds` to bound the
request. Ctrl+C terminates the child worker. The qrenderdoc UI exposes the
same operation at **Tools > Analysis Suite > Export Selected Action
Evidence**. An installed UI can set `RENDERDOC_ANALYSIS_SUITE_ROOT` to the
directory containing `draw-evidence-package`.

No donor executable, injector, or installer is used. The tool does not change
the RDC format, target process, capture, or ordinary Replay path. FBX
conversion belongs to the separate `tools/draw-package-converter` utility.
