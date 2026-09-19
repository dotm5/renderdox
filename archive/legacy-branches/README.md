# 归档:2026-09-20 下线的孤立分支尖端

本分支 **不用于开发**。它只有一个提交:改动内容只有这一个说明文件,但该提交把
2026-09-20 整理 git 树时删掉的三条孤立分支尖端作为**父提交**收了进来 ——
这样它们的对象保持可达(不会被 gc 剪掉),并随本分支一起备份在远端。

## 归档清单

| 原分支 | 尖端 SHA | 提交日期 | 主题 |
| :--- | :--- | :--- | :--- |
| `origin/renderdox-main` | `f6d8f003548f59cf2477681351c1dac3a75ba693` | 2026-08-16 19:07:39 +0800 | Define local analysis artifact boundaries |
| `origin/archive/fullstack-v145`(本地同名) | `0ed42dfba63a2ba06f160f200a1848ec22d19a46` | 2026-08-16 19:07:39 +0800 | Define local analysis artifact boundaries |
| `wip/dcomp-inject-handle`(仅本地) | `10cd06d7119eb94621489d2752c3039bb7af1cb9` | 2026-09-19 00:42:51 +0800 | wip: thread an existing process handle through the injection path |

## 前两条:内容零独有,但与主线不是祖先关系

两条 08-16 尖端打的是**同一条补丁**,`git patch-id` 均为
`9302151df5b1ce7d5148d4b5758a5f0fe624e666`,与主线提交
`2a1fcb566327658768ba7fada6eafe3060d27716`(`Define local analysis artifact boundaries`)完全相同。
两条尖端彼此也**同树(`01e4158db`)同父(`adbe6e1ce`)**,只有提交者时间差 9 秒。

主线那份是在 `535669bf1 Point project documentation at dgcore-main` 之上重放的,
所以 git 看不到祖先关系 —— 这就是它们长期显示为 unmerged 的原因。
两边唯一的文本差异是 `README.md` 的两行:归档版本里 CI 徽章与 Downloads 段落仍写
`renderdox-main`,主线已改为 `dgcore-main`。

该提交本身的改动(供追溯):删除 15 个 `reports/*` 与 2 个 `docs/*` 分析产物,
`.gitignore` 增加 `/reports/` 等排除项,README 去掉指向被删文档的链接。
那些产物现在放在工作区根(`D:\rdoc-port\docs`、`D:\rdoc-port\audit`),不进版本库。

## 第三条:唯一真正只此一份的在制品

`wip/dcomp-inject-handle` 是 2026-09-19 从工作区快照出来的未完成改动,
**未评审、未构建**,未并入主线,归档前远端也没有副本。改动量:

```
 renderdoc/os/os_specific.h             |    2 +-
 renderdoc/os/posix/posix_process.cpp   |    3 +-
 renderdoc/os/win32/sys_win32_hooks.cpp | 1058 +++++++++++++++++++++++++++++++-
 renderdoc/os/win32/win32_hook.cpp      |   48 +-
 renderdoc/os/win32/win32_process.cpp   |  113 +++-
 5 files changed, 1193 insertions(+), 31 deletions(-)
```

内容:`Process::InjectIntoProcess` 接受可选的既有进程句柄并在两个平台复用,不再重新打开目标;
`FindRemoteDLL` 改为通过该句柄枚举模块;内联钩子扩展到 kernel32/kernelbase 的进程与线程创建
(`CreateProcessW/A`、`CreateProcessInternalW/A`、`CreateRemoteThread(Ex)`、`ExitProcess`、
`TerminateProcess`)以及 advapi32 的 logon 变体。

## 怎么取回

```bash
# 1. 对象就在本分支的父提交里,直接重建分支:
git branch <名字> f6d8f003548f59cf2477681351c1dac3a75ba693
git branch <名字> 0ed42dfba63a2ba06f160f200a1848ec22d19a46
git branch wip/dcomp-inject-handle 10cd06d7119eb94621489d2752c3039bb7af1cb9

# 2. 只看不改:
git show 10cd06d7119eb94621489d2752c3039bb7af1cb9
git diff dgcore-main 10cd06d7119eb94621489d2752c3039bb7af1cb9

# 3. 万一本分支也被删:GitHub 在对象未被其 gc 前允许按 SHA 直取
git fetch origin f6d8f003548f59cf2477681351c1dac3a75ba693
```

## 备份强度说明

本文件只是可读记录;**真正的备份是父提交关系** —— 只要本分支存在于远端,
这三个尖端对象就一直可达。删掉本分支,备份即失效。
