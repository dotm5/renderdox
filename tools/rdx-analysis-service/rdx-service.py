#!/usr/bin/env python3

import argparse
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from rdx_analysis.service import JsonRpcServer, RDXService


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Local-only, read-only RDX JSON-RPC analysis service"
    )
    parser.add_argument("--qrenderdoc", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-resource-mib", type=int, default=16)
    parser.add_argument("--max-sessions", type=int, default=8)
    parser.add_argument("--workers", type=int, default=2)
    arguments = parser.parse_args(argv)
    if not os.path.isfile(arguments.qrenderdoc):
        parser.error("QRenderDoc executable does not exist")
    service = RDXService(
        arguments.qrenderdoc,
        arguments.output_root,
        arguments.timeout_seconds,
        arguments.max_resource_mib * 1024 * 1024,
        arguments.max_sessions,
    )
    JsonRpcServer(service, workers=arguments.workers).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
