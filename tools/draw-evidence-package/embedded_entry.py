"""Entry point executed by QRenderDoc's embedded Python interpreter."""

import os
import sys
import traceback


ROOT = os.environ.get("DRAW_EVIDENCE_ROOT")
if not ROOT:
    script_path = globals().get("__file__")
    if script_path:
        ROOT = os.path.dirname(os.path.abspath(script_path))
if not ROOT:
    raise RuntimeError("DRAW_EVIDENCE_ROOT is not set")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from analysis_suite_evidence.worker import main

    main()
except BaseException:
    traceback.print_exc()
finally:
    # This is a dedicated child process. SystemExit prevents the normal UI from opening.
    sys.exit(0)
