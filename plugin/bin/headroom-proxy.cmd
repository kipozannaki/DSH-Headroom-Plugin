@echo off
rem ============================================================================
rem  Headroom proxy launcher (Windows / cmd.exe)
rem
rem  Runs the local HTTP compression proxy in front of DSH's OpenAI-compatible
rem  provider, so model traffic is compressed transparently.
rem
rem  Verified against headroom-ai 0.41.0 on 2026-10-16:
rem    * --mode token is REQUIRED for real compression. The default (cache) mode
rem      freezes all but the newest turn to protect the provider prefix cache and
rem      measured compressed=0 on a 4-message request.
rem    * HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS=0 removes a 10s per-request
rem      stall (the HF tokenizer download cannot complete on a restricted
rem      network, so every request waited out the timeout).
rem    * The patched venv (setup-proxy-venv.cmd) carries the x-headroom-model
rem      header fix. `uvx` cannot be used here: it recreates an ephemeral env, so
rem      the source patch would vanish and a trailing-space model id would again
rem      kill every streaming response with `Illegal header value`.
rem
rem  Upstream: pass it as argument 1, or set HEADROOM_UPSTREAM_URL (or a
rem  pre-existing OPENAI_TARGET_API_URL). It becomes OPENAI_TARGET_API_URL --
rem  the address the proxy forwards to after compressing. There is no built-in
rem  default; the launcher exits with an error rather than guessing. Client
rem  Authorization headers are passed through unchanged, so the provider API key
rem  is the one DSH sends.
rem
rem  Workspace root resolution order:
rem    1. %HEADROOM_DSH_WORKSPACE%  (explicit override)
rem    2. two levels up from this script's directory  (plugin\bin -> workspace)
rem ============================================================================
setlocal

if not "%HEADROOM_DSH_WORKSPACE%"=="" (
  set "WS=%HEADROOM_DSH_WORKSPACE%"
) else (
  set "WS=%~dp0..\.."
)

rem --- upstream target: arg 1 > HEADROOM_UPSTREAM_URL > ambient env ------------
rem  There is deliberately NO built-in default. A proxy that silently forwards
rem  to an endpoint you did not choose would send your content and your API key
rem  somewhere unexpected, so this refuses to start instead.
if not "%~1"=="" (
  set "OPENAI_TARGET_API_URL=%~1"
) else if not "%HEADROOM_UPSTREAM_URL%"=="" (
  set "OPENAI_TARGET_API_URL=%HEADROOM_UPSTREAM_URL%"
)
if "%OPENAI_TARGET_API_URL%"=="" (
  echo.
  echo ERROR: no upstream configured. Refusing to start.
  echo.
  echo   The proxy needs to know where to forward requests. Give it one of:
  echo.
  echo     headroom-proxy.cmd https://your-provider.example/v1
  echo     set HEADROOM_UPSTREAM_URL=https://your-provider.example/v1
  echo     set OPENAI_TARGET_API_URL=https://your-provider.example/v1
  echo.
  echo   Your provider's own base URL is what you want here -- the same value
  echo   the provider would use directly, e.g. https://api.deepseek.com/v1
  echo.
  exit /b 2
)

rem --- bind address / port ----------------------------------------------------
if "%HEADROOM_PORT%"=="" set "HEADROOM_PORT=8787"
if "%HEADROOM_MODE%"=="" set "HEADROOM_MODE=token"

rem --- pin every cache/tool/state directory inside the workspace -------------
set "UV_CACHE_DIR=%WS%\.uv-cache"
set "UV_TOOL_DIR=%WS%\.uv-tools"
set "UV_TOOL_BIN_DIR=%WS%\.uv-bin"
set "TIKTOKEN_CACHE_DIR=%WS%\.tiktoken-cache"
set "HEADROOM_WORKSPACE_DIR=%WS%\.headroom"

rem --- local-first: no telemetry ---------------------------------------------
rem --- no telemetry, and no update check --------------------------------------
rem  Two independent outbound paths, each with its own switch. HEADROOM_BEACON
rem  gates the anonymous session-summary upload (on by default upstream);
rem  HEADROOM_UPDATE_CHECK gates the daily PyPI version probe and is NOT covered
rem  by the beacon switch, so it needs setting separately.
set "HEADROOM_BEACON=off"
set "HEADROOM_UPDATE_CHECK=off"

rem --- no network tokenizer fetch: it always times out here, costing 10s/req --
set "HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS=0"

if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%" 2>nul
if not exist "%UV_TOOL_DIR%" mkdir "%UV_TOOL_DIR%" 2>nul
if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%" 2>nul
if not exist "%TIKTOKEN_CACHE_DIR%" mkdir "%TIKTOKEN_CACHE_DIR%" 2>nul
if not exist "%HEADROOM_WORKSPACE_DIR%" mkdir "%HEADROOM_WORKSPACE_DIR%" 2>nul

rem --- materialize the patched venv, then re-verify the patch every run -------
rem  The setup script is idempotent: it creates the venv only when missing and
rem  then re-applies the (also idempotent) header fix, so a `pip install --upgrade`
rem  or a wiped venv cannot silently leave the proxy unpatched.
rem ----------------------------------------------------------------------------
if "%HEADROOM_PROXY_VENV%"=="" set "HEADROOM_PROXY_VENV=%WS%\.proxy-venv"
set "VENV_PY=%HEADROOM_PROXY_VENV%\Scripts\python.exe"
set "VENV_PROXY=%HEADROOM_PROXY_VENV%\Scripts\headroom.exe"

call "%~dp0setup-proxy-venv.cmd" || exit /b 1

echo Headroom proxy: http://127.0.0.1:%HEADROOM_PORT%  (mode: %HEADROOM_MODE%)
echo Upstream:       %OPENAI_TARGET_API_URL%
echo.
echo Point a provider at it with:  baseURL: http://127.0.0.1:%HEADROOM_PORT%/v1

if not exist "%VENV_PROXY%" (
  echo Headroom proxy: %VENV_PROXY% missing - falling back to `headroom` on PATH
  headroom proxy --host 127.0.0.1 --port %HEADROOM_PORT% --mode %HEADROOM_MODE%
) else (
  "%VENV_PROXY%" proxy --host 127.0.0.1 --port %HEADROOM_PORT% --mode %HEADROOM_MODE%
)
exit /b %ERRORLEVEL%
