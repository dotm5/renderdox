# Proxy Builder 0.4.1 修复与当前状态

原始记录日期：2026-10-01。状态核对日期：2026-10-22。
当前源码位于 `tools/proxy-builder`；使用契约见 [ROUTES.md](../tools/proxy-builder/ROUTES.md)。

## 已修复的架构问题

| 项 | 当前结果 | 说明 |
| --- | --- | --- |
| Core 启动依赖 SDK 导出调用 | SDK 加载槽默认 worker | DllMain 创建 worker；Core 激活独立于原件首次调用 |
| Aftermath 识别 | auto 选择 aftermath | DLL basename 和 GFSDK 导出共同匹配 |
| 旧调用路径兼容 | Aftermath/streamline-bootstrap 默认 worker | 显式 activation 保留最高优先级 |
| 转发快路径 | 原件解析和必要门槛满足后原子发布 | export 模式继续检查指定触发导出 |
| requireCore 重入 | Core/插件内部重入仅转发原件 | 外部调用等待完整 Core/插件初始化 |
| 原件备选 | 支持三种命名 | 仅文件不存在时尝试下一项；其余错误保持失败 |
| 失败处理 | 创建线程、Core、插件失败均记录状态 | requireCore 的外部调用遵守失败门槛 |

专用 `bootstrap/aftermath_proxy` 与生成运行时均采用 Core worker 和原件 InitOnce
分离的结构。默认 worker 在 loader unlock 后运行；原件在首次 SDK 调用时惰性解析。
输入原件的精确导出契约、ordinal、别名及 DATA 声明继续参与验证。

## 历史验收与后续验证

0.4.1 的记录为 25 项 Python 测试、66 项双编译器路径用例、2 项混合查询用例，
以及 512,000 次并发 ABI/raw EAT 调用。load-only、阻塞 Core 握手、三个原件改名、
坏原件、初始化重入和失败门槛均有专门用例。真实 Core 的自有进程测试达到
`state=2`、`lastError=0`。

当前 Windows CI 继续执行源码测试、双编译器原生 fixture、冻结 Builder 和解压包验收。
两个 Release 均包含生成器、模板及头文件。2026-10-06 的 DX12 closure 修复进一步
覆盖 Core 的公开 DeviceFactory root、factory parent 和 SwapChain.GetDevice 返回路径。

## 按应用验证

Core `state=2` 记录 API 握手。应用捕获结论另外记录 DLL 实际加载、设备创建时序、
RDC 生成、回放和退出状态。旧记录中的某个 PID、加载错误或原件导出数量属于当时实例；
当前应用使用当前原件契约和当前 Core 哈希验证。

```powershell
proxy-builder.exe build D:\original\GFSDK_Aftermath_Lib.x64.dll --output D:\build\aftermath --copy-original --core D:\DComp\dgcore.dll --enable-core
```
