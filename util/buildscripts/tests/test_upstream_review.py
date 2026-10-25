"""Source-only regressions for upstream review fixes; never invoke a compiler."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class UpstreamReviewTests(unittest.TestCase):
    def test_async_capture_access_never_executes_inline(self):
        body = source("qrenderdoc/Code/Interface/QRDInterface.h").split(
            "bool AccessInvoke(", 1
        )[1].split("bool BlockAccessInvoke(", 1)[0]
        asynchronous = body.split("if(!blocking)", 1)[1].split("else if(", 1)[0]
        self.assertRegex(asynchronous, r"if\(!IsRunning\(\)\)\s+return false;")
        self.assertIn("AsyncInvoke(invoke, tag)", asynchronous)
        self.assertNotIn("callback(", asynchronous)
        self.assertIn("if(ICaptureAccess *access = GetCaptureAccess())", body)
        self.assertIn("else if(CurrentRemote().IsConnected() && IsRunning())", body)

    def test_dependency_progress_waits_are_bounded_and_atomic(self):
        body = source("qrenderdoc/Code/CaptureContext.cpp").split(
            "void CaptureContext::EmbedDependentFiles()", 1
        )[1]
        for operation in ("EmbedDependenciesIntoCapture", "RemoveDependenciesFromCapture"):
            self.assertIn("access->" + operation + "()", body)
        self.assertEqual(body.count("std::atomic<bool> done(false)"), 2)
        self.assertEqual(body.count("done.store(true)"), 2)
        self.assertEqual(body.count("for(int i = 0; !done.load() && i < 100; i++)"), 2)
        self.assertEqual(body.count("[&done]() { return done.load(); }"), 2)
        self.assertNotIn("GetCurrentProcessingTag", body)

    def test_symbol_initialization_uses_the_replay_worker(self):
        body = source("qrenderdoc/Windows/MainWindow.cpp").split(
            "void MainWindow::on_action_Resolve_Symbols_triggered()", 1
        )[1].split("void MainWindow::on_action_Recompress_Capture_triggered()", 1)[0]
        self.assertNotIn("AsyncAccessInvoke", body)
        self.assertIn("!m_Ctx.Replay().GetCaptureAccess() || !m_Ctx.Replay().IsRunning()", body)
        self.assertIn("m_Ctx.Replay().AsyncInvoke(", body)
        worker = body.split("m_Ctx.Replay().AsyncInvoke(", 1)[1].split("ShowProgressDialog", 1)[0]
        self.assertIn("access->InitResolver", worker)
        self.assertIn("finished.store(true)", worker)
        self.assertIn("std::atomic<float>", body)
        self.assertIn("std::atomic<bool>", body)
        self.assertIn("finished.load()", body)
        self.assertIn("progress.load()", body)
        self.assertGreater(body.index("if(!result.OK())"), body.index("ShowProgressDialog"))

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

    def test_memory_range_barriers_use_shared_replay_mapping(self):
        commands = source("renderdoc/driver/vulkan/wrappers/vk_cmd_funcs.cpp")
        sync = source("renderdoc/driver/vulkan/wrappers/vk_sync_funcs.cpp")
        self.assertIn("RemapMemoryRangeBarriers(DependencyInfo);", commands)
        self.assertIn("RemapMemoryRangeBarriers(depInfo);", sync)
        helper = sync.split("void WrappedVulkan::RemapMemoryRangeBarriers", 1)[1].split("bool WrappedVulkan::HasDescriptorBufferBarrier", 1)[0]
        self.assertIn("RemapQueueFamilyIndices(barrier.srcQueueFamilyIndex, barrier.dstQueueFamilyIndex)", helper)

    def test_descriptor_versions_include_all_dependency_info_entries(self):
        commands = source("renderdoc/driver/vulkan/wrappers/vk_cmd_funcs.cpp")
        sync = source("renderdoc/driver/vulkan/wrappers/vk_sync_funcs.cpp")
        self.assertIn("HasDescriptorBufferBarrier(DependencyInfo)", commands)
        self.assertIn("HasDescriptorBufferBarrier(pDependencyInfos[ev])", sync)
        helper = sync.split("bool WrappedVulkan::HasDescriptorBufferBarrier", 1)[1].split("template <typename SerialiserType>", 1)[0]
        self.assertIn("ranges->pMemoryRangeBarriers[i].dstAccessMask", helper)
        self.assertIn("VK_ACCESS_2_DESCRIPTOR_BUFFER_READ_BIT_EXT", helper)

    def test_device_address_actions_record_buffer_usage(self):
        body = source("renderdoc/driver/vulkan/wrappers/vk_draw_funcs.cpp")
        checks = {
            "vkCmdCopyMemoryKHR": ("ResourceUsage::Copy", "ResourceUsage::CopySrc", "ResourceUsage::CopyDst"),
            "vkCmdFillMemoryKHR": ("ResourceUsage::Clear",),
            "vkCmdUpdateMemoryKHR": ("ResourceUsage::CopyDst",),
            "vkCmdCopyMemoryToImageKHR": ("RecordDeviceAddressUsage(CopyInfo.pRegions[i].addressRange.address, ResourceUsage::CopySrc)",),
            "vkCmdCopyImageToMemoryKHR": ("RecordDeviceAddressUsage(CopyInfo.pRegions[i].addressRange.address, ResourceUsage::CopyDst)",),
        }
        for name, required in checks.items():
            function = body.split("bool WrappedVulkan::Serialise_" + name + "(", 1)[1].split("void WrappedVulkan::" + name + "(", 1)[0]
            for text in required:
                self.assertIn(text, function)
            self.assertIn("RecordDeviceAddressUsage", function)

    def test_registered_dxil_vendor_uav_retains_compatibility(self):
        body = source("renderdoc/driver/shaders/dxbc/dxbc_container.cpp").split("bool DXBCContainer::UsesExtensionUAV(", 1)[1].split("bool DXBCContainer::CheckForDebugInfo(", 1)[0]
        self.assertIn("slot == ~0U && space == ~0U", body)
        self.assertRegex(body, r"if\(\*fourcc == FOURCC_DXIL \|\| \*fourcc == FOURCC_ILDB\)\s+return true;")


if __name__ == "__main__":
    unittest.main()
