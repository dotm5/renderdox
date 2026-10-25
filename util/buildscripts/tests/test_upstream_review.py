"""Source-only regressions for upstream review fixes; never invoke a compiler."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class UpstreamReviewTests(unittest.TestCase):
    def test_rgp_refusal_returns_before_profile_creation(self):
        body = source("qrenderdoc/Windows/MainWindow.cpp").split(
            "void MainWindow::on_action_Create_RGP_Profile_triggered()", 1
        )[1].split("void MainWindow::on_action_Attach", 1)[0]
        self.assertRegex(body, r"if\(abort\)\s+return;")
        self.assertLess(body.index("if(abort)"), body.index("QDialog popup"))

    def test_failed_save_never_enters_transfer_wait(self):
        body = source("qrenderdoc/Windows/Dialogs/LiveCapture.cpp")
        self.assertRegex(body, r'if\(success\)\s+ShowProgressDialog\(\s+this, tr\("Transferring file\."\)')

    def test_remote_access_requires_a_running_replay_worker(self):
        body = source("qrenderdoc/Code/Interface/QRDInterface.h")
        self.assertIn("if(CurrentRemote().IsConnected() && IsRunning())", body)
        self.assertIn("virtual bool IsRunning() = 0;", body)
        self.assertIn("virtual bool IsReplayThread() = 0;", body)

    def test_replay_callback_bypasses_synchronous_ui_dispatch(self):
        body = source("qrenderdoc/Code/pyrenderdoc/PythonInvokers.cpp").split(
            "struct CaptureAccessInvoker", 1
        )[1].split("struct ReplayInvoker", 1)[0]
        self.assertRegex(body, r"if\(m_Replay.IsReplayThread\(\)\)\s+invoke\(\);")
        self.assertLess(body.index("IsReplayThread()"), body.index("GUIInvoke::blockcall"))
        delegate = source("qrenderdoc/Code/pyrenderdoc/PythonInvokers.cpp").split("struct ReplayInvoker", 1)[1]
        self.assertIn("return m_Replay.IsRunning();", delegate)
        self.assertIn("return m_Replay.IsReplayThread();", delegate)

    def test_availability_targets_application_buffer_with_its_stride(self):
        body = source("renderdoc/driver/vulkan/wrappers/vk_cmd_funcs.cpp")
        body = body.split("void WrappedVulkan::vkCmdCopyQueryPoolResultsToMemoryKHR", 1)[1]
        body = body.split("if(hasAvailability)", 1)[1].split("template <typename SerialiserType>", 1)[0]
        self.assertIn("Unwrap(GetResourceManager()->GetHandle<VkBuffer>(id))", body)
        self.assertIn("offs + (i * pDstRange->stride) + resultSize", body)
        self.assertNotIn("qpInfo->m_Buffer.UnwrappedBuffer()", body)
        # Sparse strides must not overlap result data or the next query result.
        for width in (4, 8):
            for stride in (16, 32, 64):
                offsets = [4096 + i * stride + width for i in range(4)]
                self.assertEqual(offsets[1] - offsets[0], stride)
                self.assertTrue(all(offset + width <= 4096 + (i + 1) * stride for i, offset in enumerate(offsets)))

    def test_optional_counter_and_binding_arrays_reset_old_state(self):
        body = source("renderdoc/driver/vulkan/wrappers/vk_cmd_funcs.cpp")
        counters = body.split("bool WrappedVulkan::Serialise_vkCmdBeginTransformFeedback2EXT", 1)[1].split("void WrappedVulkan::vkCmdBeginTransformFeedback2EXT", 1)[0]
        self.assertIn("if(pCounterInfos)", counters)
        self.assertIn("renderstate.xfbcounters[i].buf = ResourceId();", counters)
        self.assertIn("renderstate.xfbcounters[i].offs = 0;", counters)
        bindings = body.split("bool WrappedVulkan::Serialise_vkCmdBindTransformFeedbackBuffers2EXT", 1)[1].split("void WrappedVulkan::vkCmdBindTransformFeedbackBuffers2EXT", 1)[0]
        self.assertIn("if(pBindingInfos)", bindings)
        self.assertIn("renderstate.xfbbuffers[firstBinding + i].buf = ResourceId();", bindings)
        self.assertIn("pBindingInfos ? GetResIDFromAddr", bindings)


if __name__ == "__main__":
    unittest.main()
