# Final build matrix

## Result

The code-under-test commit was
`47fa352209db1d410b39a24e685f1481f6195cb3`. Later finalization changes only
documentation/reports and generated external audit artifacts.

| Configuration | Command target | Toolset | Result | Warnings | Errors | Wall time |
|---|---|---|---|---:|---:|---:|
| Development x64 | `Build` | v143 | PASS | 0 | 0 | 20.507 s |
| Release x64 | `Build` | v143 | PASS | 0 | 0 | 926.168 s |

Development reused valid intermediates after the Qt 5.9 correction. Release
was the first Release output in this worktree, so `Build` had no usable
IPDB/IOBJ and compiled 125,904 Core functions plus 69,935 qrenderdoc
functions. Its time is therefore a first-build cost, not an incremental
product regression.

## Compatibility correction found by the gate

The first Development attempt failed in the new Evidence menu code because
the bundled Qt 5.9 does not provide `qEnvironmentVariable` or
`QUuid::WithoutBraces`. Commit `284363a9f` replaced them with
`QProcessEnvironment::systemEnvironment().value()` and a Qt 5.9-compatible
UUID string slice. The final Development and Release builds both passed.

## Evidence

- `audit/followup/final-validation/development-x64-build-final.log`
- `audit/followup/final-validation/development-x64-build-final.binlog`
- `audit/followup/final-validation/release-x64-build-final.log`
- `audit/followup/final-validation/release-x64-build-final.binlog`

Both output directories contain the expected Core, UI, command, shim, and
Python-binding artifacts.
