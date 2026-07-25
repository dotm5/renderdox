"""Entry point executed by QRenderDoc's embedded Python interpreter."""

import os
import sys
import traceback


ROOT = os.environ.get("RDX_ACTION_VIS_ROOT")
if not ROOT:
    script_path = globals().get("__file__")
    if script_path:
        ROOT = os.path.dirname(os.path.abspath(script_path))
if not ROOT:
    raise RuntimeError("RDX_ACTION_VIS_ROOT is not set by the test launcher")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def progress(stage):
    path = os.environ.get("RDX_ACTION_VIS_PROGRESS")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(stage + "\n")
            stream.flush()
    except OSError:
        pass


try:
    progress("entry-start")
    from worker import main

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
