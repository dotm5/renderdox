# Proxy Builder 0.4.1

只读解析输入 PE，在新目录生成、编译并验证 x64 代理。便携 `proxy-builder.exe`
自带 Python；编译需要 Visual Studio C++/MASM，JVM 宿主额外需要 JDK。
完整配置见 [ROUTES.md](ROUTES.md)，版本结论见 [实现状态](../../docs/current-status.md)。

## 当前生成路径

`build` 默认使用统一运行时和 `--profile auto`。auto 根据 DLL basename 与已知接口
选择 profile；`--route` 保留 system-dll、app-local、streamline-bootstrap 三种路由标记。

| Profile | 行为 |
| --- | --- |
| generic | 精确函数导出、provider 链、激活和插件配置 |
| aftermath | Core worker 与惰性 SDK 转发独立，支持三个原件改名 |
| streamline | 物理 EAT stub 与已有 Core provider 接入 |
| ngx | 精确 SDK 转发及可配置激活 |
| nvapi | 数字查询分发，保留未知 ID、NULL 与原件返回地址 |
| vulkan | instance/device 查询分别转发，保留 handle |
| agility | D3D12GetInterface 及显式 DATA 契约 |

```powershell
proxy-builder.exe profiles
proxy-builder.exe build D:\original\vendor.dll --output D:\proxy-build\vendor --copy-original
proxy-builder.exe build C:\Windows\System32\dxgi.dll --output D:\proxy-build\dxgi --toolchain ClangCL
proxy-builder.exe build D:\original\GFSDK_Aftermath_Lib.x64.dll --output D:\proxy-build\aftermath --copy-original --core D:\DComp\dgcore.dll --enable-core
```

默认图形 provider 使用 first-call；SDK/普通加载槽使用 worker。支持 worker、first-call、
export、entry-point、manual、module-load 六种 activation，显式配置优先。
Aftermath 即使沿用 streamline profile 或 streamline-bootstrap 路由，仍默认使用 worker。
Core 激活与原件首次解析分别初始化；满足门槛后发布 ASM 快路径。

`--copy-original` 复制 sibling 原件，`--core` 验证并复制 Core，`--enable-core` 创建
`dgcore.enable`。已有内容的输出目录拒绝覆盖；输入、源码、头文件和产物绑定 SHA256。
成功输出 `build.log`、`build-result.json`、`exports.json` 和可独立重编译的工程。

## DATA 导出

统一运行时支持显式 DATA 声明。例：输入 D3D12 DLL 包含非执行区导出时，保存配置：

```json
{
  "provider":{"kind":"sibling","path":"d3d12_orig.dll"},
  "dataExports":{"D3D12DeviceRemovedExtendedData":{"type":"opaque-address"}},
  "activation":"first-call"
}
```

```powershell
proxy-builder.exe build D:\original\d3d12.dll --output D:\proxy-build\d3d12 --profile agility --config data.json --copy-original
```

DATA 使用指向原件存储的 PE forwarder，并生成经过验证的类型化导入库。原件须满足
loader 的 DLL 搜索规则。纯 DATA 导入可先于代理 DllMain；DATA/linker 转发直接由 loader
解析，物理函数 stub 的 activation 与运行时检查在其自身路径执行。

## 旧模板入口

`generate --template system/app-local` 在省略 profile/config 时保留 0.3.1 模板。
该兼容入口仍拒绝 DATA/未知导出；图形系统模板限 DXGI/D3D11/D3D12。
需要当前统一运行时时，使用 `build`，或为 `generate` 显式传入 profile/config。

## 验证

```powershell
python -m unittest discover -s tools/proxy-builder/tests -p test*.py
python tools/proxy-builder/tests/run_route_acceptance.py --output D:\route-acceptance --toolchain Both
pwsh -NoProfile -File tools/proxy-builder/tests/run_static_acceptance.ps1 -Python C:\Python312\python.exe -OutputDirectory D:\legacy-acceptance
```

原生用例覆盖双编译器 ABI/raw EAT、DATA、查询分发、原件链、激活时序和宿主。
`status=verified` 验证编译、导出契约及哈希；Core `state=2` 记录 API 握手。
实际应用另行记录加载链、设备包装、RDC 生成与回放。
专用 43-name union Aftermath proxy 保持独立，生成器匹配每份输入原件的精确契约。
