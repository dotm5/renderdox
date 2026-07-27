@echo off
setlocal

set "SCRIPT=%~dp0util\buildscripts\build_windows_release.ps1"
"C:\Program Files\PowerShell\7\pwsh.exe" -NoLogo -NoProfile -File "%SCRIPT%" -Target Rebuild -Platform x64
set "BUILD_EXIT=%ERRORLEVEL%"

if not "%BUILD_EXIT%"=="0" (
  echo.
  echo === RELEASE BUILD FAILED: %BUILD_EXIT% ===
  exit /b %BUILD_EXIT%
)

echo.
echo === RELEASE BUILD SUCCESS ===
exit /b 0
