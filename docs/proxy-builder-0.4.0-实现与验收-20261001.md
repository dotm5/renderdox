# Proxy Builder 0.4.0 历史实现与后续状态

原始记录日期：2026-10-01。状态核对日期：2026-10-22。
当前版本为 0.4.1；配置和命令见 [ROUTES.md](../tools/proxy-builder/ROUTES.md)。

## 已实现机制

0.4.0 引入统一运行时、物理 x64 EAT stub、system/sibling/absolute provider 链、
NVAPI/Vulkan 查询分发、显式 DATA forwarder、六种 activation，以及 ASI、JVM、
OpenXR 和 Vulkan Layer 宿主。导出名称、ordinal、别名及输入/产物哈希均参与验证。

当时有 generic、streamline、ngx、nvapi、vulkan、agility 六种 profile。
0.4.1 新增专用 aftermath profile，当前合计七种。

## 后续修复

| 项 | 当前结果 | 说明 |
| --- | --- | --- |
| SDK/普通加载槽依赖首次调用 | 0.4.1 默认 worker | Aftermath、generic、NGX、NVAPI 与普通系统槽在 DLL 加载后独立启动 Core |
| 每次转发进入 resolver | 已发布 ASM 快路径 | 初始化和必要门槛完成后切换；export activation 保留触发检查 |
| requireCore 握手重入失败 | 已修复 | 初始化内部重入转发原件；外部调用等待完整初始化 |
| Aftermath 原件改名 | 支持三种既有命名 | 仅原件不存在时尝试备选；哈希、依赖或契约失败直接报告 |
| D3D12 public DeviceFactory 包装 | 2026-10-06 已补齐 Core 路径 | 对应 DX12 closure 样例验证接口身份与引用计数 |

## 历史验收

0.4.0 的记录为 19 项 Python 测试、40 项双编译器路径用例、2 项混合查询用例，
以及 512,000 次 ABI/raw EAT 调用。显式 DATA 的 D3D12 产物和 OpenXR/Vulkan
宿主构建均有当时的验收记录。后续用例见 0.4.1 记录及当前源码测试。

## 当前适用条件

- `status=verified` 验证编译、导出契约和哈希；Core `state=2` 记录 API 握手。
- DATA/linker forwarder 由 loader 解析；原件需要满足正常 DLL 搜索规则。
- entry-point 用于启动期加载；first-call 要在 loader lock 外且早于目标对象创建。
- worker 和 module-load 按异步时序执行，实际接入顺序按应用记录。
- 自动生成器匹配输入原件的精确契约；专用 43-name union proxy 独立维护。

输入 DLL 保持只读；输出使用新目录。Visual Studio C++/MASM 为编译依赖，JVM 宿主
额外需要 JDK。Khronos 头文件来源和固定摘要见 vendor/openxr/PROVENANCE.json。
