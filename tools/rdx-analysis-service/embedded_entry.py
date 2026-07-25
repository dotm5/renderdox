"""Entry point executed by QRenderDoc's embedded Python interpreter."""

import os
import sys
import traceback


HERE = os.environ.get("RDX_ANALYSIS_ROOT")
if not HERE:
    script_path = globals().get("__file__")
    if script_path:
        HERE = os.path.dirname(os.path.abspath(script_path))
if not HERE:
    raise RuntimeError("RDX_ANALYSIS_ROOT is not set by the analysis launcher")
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def progress(stage):
    path = os.environ.get("RDX_ANALYSIS_PROGRESS")
    if not path:
        return
    try:
        with open(path, "a") as stream:
            stream.write(stage + "\n")
            stream.flush()
    except OSError:
        pass


try:
    progress("entry-start")
    from rdx_analysis.embedded_worker import main

    progress("worker-imported")
    main()
    progress("worker-returned")
except BaseException:
    progress("entry-exception")
    traceback.print_exc()
finally:
    progress("entry-exit")
    # QRenderDoc treats SystemExit as a request to skip opening the UI.
    sys.exit(0)
