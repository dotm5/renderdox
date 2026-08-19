# DComp staged injection loader

`dgbootstrap.dll` is a small explicit-injection entry point. Its `DllMain` only
schedules a worker and returns. The worker then loads the adjacent product core
(`dgcore.dll`) by absolute path.

Place both DLLs in the same directory and select `dgbootstrap.dll` in the
injector. Do not rename the loader to `dgcore.dll`.

The worker delay defaults to 32 ms. It is a scheduling heuristic, not a
synchronisation guarantee. Override it with either:

- environment variable `DCOMP_STAGE_DELAY_MS`; or
- an ASCII integer in adjacent `dgbootstrap.delay-ms`.

Values from 0 through 2000 ms are accepted. The environment variable takes
precedence over the file. Worker stages and load results are appended to
adjacent `dgbootstrap.log`.

Exported status values are:

- `DGBootstrap_GetState`: 1 scheduled, 2 worker started, 3 waiting, 4 loading,
  5 loaded; the high bit marks failure.
- `DGBootstrap_GetLastError`: the Win32 error for the latest failure.
- `DGBootstrap_GetDelayMs`: the selected delay.
