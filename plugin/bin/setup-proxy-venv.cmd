@echo off
rem ============================================================================
rem  Build the patched Headroom proxy environment (Windows / cmd.exe).
rem
rem  Why a dedicated venv instead of `uvx`:
rem    `uvx --from headroom-ai[proxy]` recreates an ephemeral env pointed at the
rem    public wheel, so a source patch cannot survive. This script materializes a
rem    venv the launcher then runs, and applies the header fix into it.
rem
rem  The fix (see patch_headroom_model_header.py) makes `x-headroom-model`
rem  HTTP-legal. Without it a model id carrying a trailing space -- which the
rem  DeepSeek Harness model picker produces -- makes h11 reject the whole response
rem  after upstream already answered 200:
rem      h11._util.LocalProtocolError: Illegal header value b'deepseek-v4.1-flash '
rem
rem  Idempotent: re-running only re-verifies. Delete the venv directory to rebuild.
rem ============================================================================
setlocal

if not "%HEADROOM_DSH_WORKSPACE%"=="" (
  set "WS=%HEADROOM_DSH_WORKSPACE%"
) else (
  set "WS=%~dp0..\.."
)

if "%HEADROOM_PROXY_VENV%"=="" set "HEADROOM_PROXY_VENV=%WS%\.proxy-venv"
if "%HEADROOM_PYTHON%"=="" set "HEADROOM_PYTHON=3.12"
if "%HEADROOM_PROXY_EXTRAS%"=="" set "HEADROOM_PROXY_EXTRAS=proxy"

set "UV_CACHE_DIR=%WS%\.uv-cache"
set "UV_TOOL_DIR=%WS%\.uv-tools"
set "UV_TOOL_BIN_DIR=%WS%\.uv-bin"

set "VENV_PY=%HEADROOM_PROXY_VENV%\Scripts\python.exe"
set "PATCHER=%~dp0..\patch_headroom_model_header.py"

if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%" 2>nul
if not exist "%UV_TOOL_DIR%" mkdir "%UV_TOOL_DIR%" 2>nul
if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%" 2>nul

if not exist "%VENV_PY%" (
  echo [setup] creating venv at %HEADROOM_PROXY_VENV%
  uv venv --python %HEADROOM_PYTHON% "%HEADROOM_PROXY_VENV%" || exit /b 1
  echo [setup] installing headroom-ai[%HEADROOM_PROXY_EXTRAS%]
  uv pip install --python "%VENV_PY%" "headroom-ai[%HEADROOM_PROXY_EXTRAS%]" || exit /b 1
)

echo [setup] applying header-safety patch
"%VENV_PY%" "%PATCHER%" --target "%HEADROOM_PROXY_VENV%\Lib\site-packages\headroom" || exit /b 1

echo [setup] done: %HEADROOM_PROXY_VENV%
exit /b 0
