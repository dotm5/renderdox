# RenderDoc portable MCP

本服务通过公共 Python API 提供捕获、回放、资源调查、事件 Diff 和跨 RDC 对齐。
RenderDoc 核心、驱动和原生数据结构没有新增依赖。服务运行时和原生 Worker 分进程，
Worker 串行拥有 ReplayController/TargetControl；取消请求不会释放仍在执行的原生事务。

## 便携使用

解压完整包，在客户端添加 `renderdoc-mcp.exe serve --stdio`。
无需系统 Python、pip 或安装程序。入口支持中文路径和从其他工作目录启动。

```powershell
./renderdoc-mcp.exe config
./renderdoc-mcp.exe config --format codex
./renderdoc-mcp.exe --output-dir 'F:\mcp-results' serve --stdio
```

`config` 只打印配置。移动便携包后重新生成配置。
默认产物在 `%LOCALAPPDATA%\RenderDocMCP\data`；通过 `--output-dir` 选择持久目录。
同一目录已由另一服务持有时，自动创建独立实例子目录，不共享原生会话。
`mcp/component-manifest.json` 记录核心来源、ABI、服务运行时和依赖。

## 推荐调查流程

1. `get_capabilities` 查看包与运行时。
2. `open_capture(path=...)` 返回 jobId；`get_job` 完成后获得 sessionId、captureId。
3. `find_actions`、`list_resources` 先过滤定位，再调用 `get_draw_evidence`。
4. `get_constants` 可同时取得成员布局、描述符偏移、值和原始字节。
5. `get_shader` 返回反射、字节码产物、分页/搜索反汇编。
6. `view_texture` 返回显示预览；`read_texture`、`sample_pixels` 用于原始数值。
7. `diff_event` 返回前后资源、数值差异和变化热图。无变化不等于没有绘制物件。
8. 多份 captureId 建立 `create_capture_set`；`align_events` 返回任务和 alignmentId。
9. `get_aligned_event` 查看匹配理由/候选；歧义用 `override_alignment` 或明确 targetEventId。
10. `diff_aligned_events`、`compare_aligned_constants` 比较对应输出和常量。

所有 EID/ResourceId 必须与 captureId/sessionId 一起理解。集合排序不是时间连续性的证明。
自动对齐使用 Pass 标记、Shader 字节码哈希、索引数据、输出描述、拓扑和绘制参数。
可额外开启纹理内容哈希；这会增加 GPU 读取时间。
自动匹配保留歧义、一对多人工锚点、多对一和未找到，不强行生成单一对应关系。

## 运行时捕获

`list_targets` 只发现启用了 RenderDoc 的目标，不连接目标。
`connect_target` 默认报告已有控制客户端；`takeover=true` 才强制接管。
不要让 GUI 和 MCP 同时争用同一个控制连接。

`capture_sequence(connectionId, count=10, intervalSeconds=1, framesPerCapture=1)` 返回 jobId。
count 是触发轮数；返回实际收到帧数和 RDC 数。上一轮未结束会延后下一轮，避免补发突发。
Worker 在等待任务完成期间持续 ReceiveMessage，复制完成消息到达后才将 RDC 记为 ready。
默认完成等待 120 秒，可用 completionTimeoutSeconds 调整。
`stop_job` 是协作停止；已开始的原生操作/复制结束后清理，不终止目标进程。
API 没有逐请求 token，所以收到的捕获只标记为时间/连接候选；额外捕获记录归属歧义。

`capture_after`、`capture_at_frame`、`save_capture`、`cycle_capture_window` 同样可用。
`launch_and_capture` 和 `inject_process` 封装公共启动/注入接口，返回控制连接。
捕获仅收集已知目标数据，不自动删除目标上的源捕获。

## Diff 范围

原始数值支持 regular 整数/浮点/UNorm/SNorm、R10G10B10A2、R11G11B10、D24S8/D32S8。
BC/ASTC/ETC/YUV 或不认识的布局保留原始产物并报告不可用，不把 PNG 冒充原始值。
不同分辨率或格式不会隐式缩放/重新解释。
3D 纹理读取整个 mip；数值比较整个体积，热图显示最大投影。
ROI 为 `[x0,y0,x1,y1]`，channels 为分量索引；绝对/相对阈值共同生效。
动作隐藏 API 可用时，同一事件省略该动作取得前态；否则使用公开 API 中前一个真实 APIEvent，
结果注明边界。Clear/Copy/Dispatch 的适用情况按实际后端能力返回。
相机、动画、TAA、曝光变化可能混入差异，当前不进行隐式运动补偿或因果判断。

## 高级回放

`get_pipeline_state`、`get_mesh`、`get_post_vs_data`、`get_resource_usage`、`trace_resource_flow`、
`pixel_history`、`debug_shader`、`replace_shader` 和 `restore_replacement` 都通过所属 Worker 执行。
PixelHistory/Debug 的支持按当前 API/Shader 实际能力报告；调试轨迹写 JSON，finally 释放原生 trace。
Shader 替换在关闭会话时恢复并释放资源；原始 RDC 不被修改。
图片通过 MCP ImageContent 返回，其他产物提供 resource_link，可由 resources/read 获取。

## 0.2 分析工具（共 66 个工具）

下列耗时工作流返回 jobId，通过 `get_job` 获取完成结果。所有原生查询仍走所属 Worker 的串行队列；
联系表、数值遮罩、匹配评分、曲线和 ZIP 等 CPU 工作在服务侧线程执行。

| 工具 | 用途 |
| --- | --- |
| `locate_draws_at_pixel` | 指定输出、EID 和 mip 像素坐标，联结 Pixel History、事件、Shader 绑定和失败原因；不自动推断最终屏幕背后的所有场景绘制 |
| `visualize_draw_contribution` | 指定绘制的一个或多个输出，生成数值变化遮罩、叠加图、包围框和局部图；结果注明前态取得方法 |
| `preview_resources` | 纹理联系表，含 ID、尺寸、格式、名称和使用事件；支持资源筛选、分页、通道、mip/slice/sample 和显示范围 |
| `trace_output_dependencies` | 反向资源读写图，保留复合目标的多次写入及可能的 UAV 写入；返回分页节点/边、完整 JSON 和 Mermaid |
| `group_related_draws` | 根据索引内容、顶点绑定、可选顶点范围内容、拓扑和绘制参数寻找关联几何；可附常量差异 |
| `list_gpu_counters` | 枚举当前后端实际支持的计数器、类型和单位，直接返回结果 |
| `profile_events` | 采集 GPU 计数器，按事件排序、按完整 marker 路径聚合；完整结果另存 JSON |
| `match_resources` | 跨捕获资源候选：布局、指定事件的内容、Shader/绑定用途、名称；不使用 ResourceId 数值相等作为身份依据 |
| `track_constant_changes` | 对齐集合中的常量值轨迹，导出完整 JSON、CSV 和曲线；歧义对应保持缺失，不自动填充 |
| `summarize_capture_changes` | 区分明确匹配、歧义、未匹配以及管线/常量/对应输出变化；不把 EID 移动当作新增对象 |
| `get_event_api_calls` | 事件附近的结构化调用参数，支持调用名称筛选、分页、参数深度和数组分页摘要，直接返回结果 |
| `query_shader_trace` | 查询 `debug_shader` 保存的轨迹，按变量、步骤、下一条指令、事件标志筛选或获取最后写入，直接返回结果 |
| `annotate_capture` / `list_annotations` | 持久化捕获、事件、资源、常量偏移的注释和标签，直接返回结果；annotationId 可更新已有注释 |
| `export_analysis_bundle` | 导出 Markdown、JSON、选定事件证据和图片等产物，ZIP 内使用相对路径；可选择附带 RDC |
| `batch_query` | 有序批量只读查询，支持字段投影和逐项错误；一个查询失败不丢弃其余结果 |

例如先为角色的 GBuffer 输出建立联系表，再定位其变化区域：

```json
{"name":"preview_resources","arguments":{"sessionId":"session-...","eventId":100,"limit":12,"channels":[0,1,2]}}
{"name":"visualize_draw_contribution","arguments":{"sessionId":"session-...","eventId":100,"resourceIds":["ResourceId::123"],"threshold":0.00001}}
{"name":"group_related_draws","arguments":{"sessionId":"session-...","eventId":100,"includeGeometryHashes":true,"includeConstants":true}}
```

上述 EID/ID 仅作格式示例。联系表或像素历史不必从最终输出开始；最终画面通常已经过合成，
要定位主体绘制可以转到依赖图中的 GBuffer、深度或中间颜色目标。
贡献遮罩是选定输出变化，不等于物件轮廓分割；同一网格可能用于不同物件、实例或变换。
GPU 计数器来自回放采样，不能作为游戏实时 FPS 或端到端捕获开销。
纹理内容指纹采样 mip0/slice0/sample0，buffer 指纹覆盖整个 buffer；动态资源仍可能匹配，需结合用途候选。
快照缓存属于当前原生会话，Shader 替换/恢复时失效，不跨捕获复用管线状态。

批量查询示例：

```json
{"name":"batch_query","arguments":{"queries":[
  {"tool":"get_action","arguments":{"sessionId":"session-...","eventId":100},"fields":["eventId","numIndices"]},
  {"tool":"get_pipeline_state","arguments":{"sessionId":"session-...","eventId":100},"fields":["topology","shaders.0.stage"]}
]}}
```

## 可选 GUI 桥接

```powershell
./renderdoc-mcp.exe install-gui-bridge
```

在 GUI 的扩展管理器启用 **RenderDoc MCP Bridge**。`gui_status` 查询当前捕获，
`gui_select_event` 打开保存的 RDC 并选择 EID。桥接使用公开 GUI API、UI 线程定时器和独立消息队列，
不复用/接管 GUI 的实时目标连接。禁用扩展会关闭桥接端点。

## 开发和云端打包

服务源码位于 `tools/renderdoc-mcp`。现代服务需要 Python 3.12 和 packaging/requirements.txt；
Worker 源码保持 Python 3.6 语法，ABI 当前为 python36.dll。
更换上游 Python ABI 时，在 packaging/bundle.py 添加经确认的 embedded runtime 版本/哈希；
API 差异集中在 adapters/renderdoc，MCP/Workflow 不引用 SWIG 对象。

```powershell
python packaging/bundle.py --package-root 'D:\cloud-package' --build-root 'D:\mcp-build'
```

打包只冻结服务并补充 Worker，不编译 RenderDoc。MSBuild Action 在生成 MSVC/ClangCL 包后运行此步骤，
更新包清单、矩阵清单并沿用现有 DLL closure 和 ZIP 检查。
