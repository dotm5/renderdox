# dgcore 成功注入路线与故障归因（2026-08-16）

## 结论

当前可工作的路线是：使用已经通过实测的新注入器加载静态运行库版
`dgcore.dll`，让它接管 DX 设备，再用官方 RenderDoc GUI 连接目标进程。
实测结果包括游戏可正常进入、叠加层出现、GUI 可 Attach、生成的 RDC 可读取。

保留两个正式构建：

- `recursive-one-generation`：注入当前进程创建的直接子进程，随后关闭继续递归。
  这是启动器到 Shipping 进程场景的首选版本，影响面最小。
- `recursive-all-generations`：每一代被注入进程继续向其子进程传播。只有目标渲染进程
  不在第一代时才使用。

两者均为 x64 Release、v143、Windows SDK 10.0.26100.0，Core 完整链接图统一
使用 `/MT`，并启用默认子进程 Hook 与原生 DX 入口 Hook。诊断隔离开关全部关闭。
产品文件名保持为 `dgcore.dll`，避免与系统 `dcomp.dll` 发生名称冲突。

## 证据与归因

### 已确认

1. 旧构建存在 MSVC 运行库边界不一致的问题；注入 DLL 的完整静态库链接图没有统一
   `/MT` 时，会重新引入目标机器上的动态 CRT 装载条件。正式构建现已统一 `/MT`，并在
   交付时检查不得导入 `MSVCP*.dll`、`VCRUNTIME*.dll` 或 `ucrtbase.dll`。
2. x64dbg 路线下，即使只加载不进入 Shipping 的最小 `089` DLL，游戏仍会出现
   “页面动画和按钮按压存在，但进入大厅动作不执行”的现象。该 DLL 不包含 RenderDoc
   图形 Hook，因此交互问题不能归因于叠加层、DX Hook 或 GUI 通信。
3. 同一目标换用新的注入器后，加载完整 dgcore 仍能正常交互并完成截帧。因此注入方式、
   注入时机或调试器维持的进程状态，是交互故障的决定性变量。
4. 当前 DLL 已在实际目标中出现叠加层，官方 GUI 可以 Attach，生成的 RDC 可以读取。
   这证明 DX 接管、目标控制通信和捕获文件链路同时成立。

### 强推断

- x64dbg 注入可能留下线程暂停计数、调试异常继续状态、焦点/输入状态，或改变启动器与
  子进程建立 IPC 的时序。渲染和局部 UI Hit Test 仍工作，而依赖异步任务、IPC 或状态机
  的“进入大厅”不执行，与这类部分初始化/调度异常相符。
- 早期混合 CRT 构建会放大远程 `LoadLibrary` 初始化、线程局部存储和异常处理边界上的
  不稳定性，因此它是旧版“载入失败/退出”的重要原因。

### 尚未确认

- `KMODE_EXCEPTION_NOT_HANDLED` 的具体内核栈尚未由对应 dump 锁定。用户态 CRT
  依赖错误本身不能直接解释内核蓝屏；它最多可能触发了注入器驱动、调试驱动或图形内核
  路径中的缺陷。没有 dump 栈前，不应把蓝屏单独归因于 dgcore 或 CRT。
- x64dbg 路线究竟是暂停计数、远程线程、调试端口还是输入/IPC 时序造成交互失败，尚未
  缩小到单一机制。由于替换注入器已经恢复完整功能，生产采集路线无需继续承担该风险。

## 推荐操作

1. 离线测试优先使用 `recursive-one-generation`。
2. 用已验证的新注入器加载启动器；不要在 CE 暂停或 x64dbg 入口断点挂起期间注入。
3. 等目标 Shipping 进程出现叠加层后，再从官方 RenderDoc GUI Attach。
4. 先验证能正常进入目标场景，再开启最高画质并截帧。
5. 仅当日志证明渲染进程位于第二代或更深层级时，改用
   `recursive-all-generations`。
6. 同一次实验只改变 DLL 版本或注入器之一，记录进程树、注入时刻、叠加层、交互与 RDC
   五项结果。

## 构建与交付边界

- 可复现脚本：`util/buildscripts/build_dgcore_injection_variants.ps1`
- 输出只保留两套 DLL、每套构建属性与二进制检查结果，以及总清单。
- 仓库已转为 Core DLL 构建边界，删除旧代理实验、内置 qrenderdoc 依赖副本和历史生成物；
  GUI 使用外部官方 RenderDoc，不随此仓库交付。
- 清理前无法确认是否仍有参考价值的临时日志与原型没有销毁，保存在仓库外：
  `D:\rdoc-port\artifacts\dcomp-isolated-cleanup-backup-20260816`。

## 验收标准

- DLL 导出 `DCOMP_GetAPI`。
- DLL 不动态依赖 MSVC C/C++ 运行库。
- 一层版只传播到直接子进程；全量版可继续传播到后代进程。
- 本地原生链路测试可创建 D3D11 SwapChain、D3D12 Device，并完成捕获。
- 目标实测必须同时满足：可交互、叠加层出现、GUI Attach 成功、RDC 可读取。
