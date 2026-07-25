"""Entry point for one isolated RDX query worker."""

import os
import sys
import traceback


ROOT = os.environ.get("RDX_QUERY_ROOT")
if not ROOT:
    script_path = globals().get("__file__")
    if script_path:
        ROOT = os.path.dirname(os.path.abspath(script_path))
if not ROOT:
    raise RuntimeError("RDX_QUERY_ROOT is not set")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from rdx_analysis.query_worker import main

    main()
except BaseException:
    traceback.print_exc()
finally:
    sys.exit(0)
