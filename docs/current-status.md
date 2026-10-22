# 实现状态与历史结论对齐

核对日期：2026-10-22。源码基线：`0e6014a6f320`；原生版本为 RenderDoc v1.46，
已集成上游 `36b1c78ec`。历史记录中的测试日期和测量值保留其原构建范围；
下表给出当前实现、后续修复和仍需按应用运行的验证。

| 项 | 当前结论 | 依据 |
| --- | --- | --- |
| MCP 版本与工具数 | 0.3.2，72 个工具；66、70 分别属于 0.2、0.3.1 | `tools/renderdoc-mcp/contracts/__init__.py`、`contracts/catalog.py` |
| Proxy Builder | 0.4.1，7 种 profile、6 种 activation | `tools/proxy-builder/routes.py`、`ROUTES.md` |
| D3D12 DATA 导出 | 统一运行时支持显式 `dataExports`、PE forwarder 和类型化导入库；旧模板入口继续拒绝数据/未知导出 | `routes.py::config_for/generate/verify_data_imports` |
| Aftermath 默认启动 | worker 独立激活 Core；原件在 SDK 首次调用时惰性解析；显式 activation 优先 | `routes.py::activation_default`、`templates/route_runtime.cpp` |
| 0.4.0 转发与重入问题 | 0.4.1 已修复快路径发布和 requireCore 初始化重入；外部调用等待所需初始化 | `templates/route_runtime.cpp`、`tests/run_route_acceptance.py` |
| D3D12 接口返回路径 | 2026-10-06 已修复公开 DeviceFactory root、DXGI parent factory identity 和 SwapChain.GetDevice 包装/引用计数 | `renderdoc/driver/d3d12`、`renderdoc/driver/dxgi`、`tools/dx12-closure` |
| 捕获附件导出 | 0.3.2 已收集嵌套 capture 附件；当前便携构建包含该修复 | `workflows/analysis.py`、`test_bundle_includes_nested_capture_artifacts` |
| Capture Doctor | 已运行过创建顺序样例；schemaVersion 2 逐项核验 EXE/Core/JSONL/RDC 哈希，独立返回 orderMatrixEvidence | `workflows/doctor.py`、`tools/capture-doctor` |
| 创建顺序的旧失败值 | 2026-10-01 的 after-factory/after-swapchain 结果属于当时 Core；当前 Core 的结论由匹配其哈希的新矩阵提供 | `doctor.py::order_matrix_evidence` |
| 发布包 bootstrap | 两套 Windows 包均包含 DXGI、D3D11、D3D12、专用 Aftermath proxy；应用部署和 Core 激活由使用者选择 | `bootstrap/README.md`、`.github/workflows/msbuild.yml` |
| Aftermath 部署检查 | 使用 `bootstrap/aftermath_proxy`；旧 gfsdk_aftermath_stub 保留为独立诊断项目 | `check_windows_deployment_subset.py` |
| 构建缓存 | 并行原生构建、完整原生包、编译结果、fixture 缓存均已接入；fixture 恢复后重新执行验收 | `.github/workflows/msbuild.yml`、`util/buildscripts/README.md` |

## 验证范围

生成器的 `status=verified` 记录编译、导出契约及产物哈希。Core `state=2` 记录 API
握手。应用捕获成功由该应用的加载链、创建顺序、RDC 生成和回放结果共同记录。

图形 provider 默认 first-call；SDK/普通加载槽默认 worker。worker 和 module-load
为异步启动；对设备创建时序有要求时，应选择并验证相应 activation。

DX12 closure 的历史样例矩阵覆盖已修复的返回接口路径。任意 vendor/private IID、
跨 Windows build 的全量接口覆盖及关闭诊断后的性能测量继续按目标运行。

## 持续适用的能力限制

原始 HLSL/语义名称自动恢复、任意 DXBC 全帧中间量插桩、通用 cbuffer 覆写和
文章实验的一键编排仍属于待实现功能。已提供的 Shader 替换、回放取数和导出接口
可用于显式实验。Mesh/ray dispatch 的 Action Visibility 支持范围仍以当前资格检查为准。

Draw Evidence 导出器将原始 Shader 容器标为 unknown；MCP 的其他 Shader 查询工具
按各自契约返回字节。两套工具的输出字段应分别读取。
