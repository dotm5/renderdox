import os
import subprocess
import tempfile
import unittest
from unittest import mock

from rdx_analysis.launcher import run_worker


class _TimedOutProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def wait(self, timeout=None):
        if not self.terminated:
            raise subprocess.TimeoutExpired("dgcoreui", timeout)
        self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def poll(self):
        return None if not self.terminated else self.returncode


class LauncherTests(unittest.TestCase):
    def test_timeout_is_bounded_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = os.path.join(directory, "capture.rdc")
            entry = os.path.join(directory, "entry.py")
            qrenderdoc = os.path.join(directory, "dgcoreui.exe")
            for path in (capture, entry, qrenderdoc):
                with open(path, "wb") as stream:
                    stream.write(b"fixture")

            process = _TimedOutProcess()
            with mock.patch(
                "rdx_analysis.launcher.subprocess.Popen", return_value=process
            ):
                result = run_worker(
                    qrenderdoc, entry, capture, os.path.join(directory, "workers"), 1
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["workerFailure"]["reason"], "timeout")
            self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()
