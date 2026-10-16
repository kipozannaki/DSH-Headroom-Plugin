@echo off
rem ============================================================================
rem  Headroom MCP server launcher (Windows / cmd.exe)
rem
rem  Starts `headroom mcp serve` over stdio for the DSH mcp-client plugin.
rem  All uv + Headroom state is pinned inside the workspace so that a sandboxed
rem  harness (workspace-write) can read/write everything it needs.
rem
rem  Workspace root resolution order:
rem    1. %HEADROOM_DSH_WORKSPACE%  (explicit override)
rem    2. two levels up from this script's directory  (plugin\bin -> workspace)
rem ============================================================================
setlocal

set "HEADROOM_WORKSPACE_DIR_OVERRIDE=%HEADROOM_DSH_WORKSPACE%"

if not "%HEADROOM_WORKSPACE_DIR_OVERRIDE%"=="" (
  set "WS=%HEADROOM_WORKSPACE_DIR_OVERRIDE%"
) else (
  set "WS=%~dp0..\.."
)

rem --- pin every cache/tool/state directory inside the workspace -------------
set "UV_CACHE_DIR=%WS%\.uv-cache"
set "UV_TOOL_DIR=%WS%\.uv-tools"
set "UV_TOOL_BIN_DIR=%WS%\.uv-bin"
set "TIKTOKEN_CACHE_DIR=%WS%\.tiktoken-cache"
set "HEADROOM_WORKSPACE_DIR=%WS%\.headroom"

rem --- local-first: no telemetry, no network surprises -----------------------
rem  Two independent outbound paths: the beacon (gated by HEADROOM_BEACON) and the
rem  daily PyPI update probe (gated by HEADROOM_UPDATE_CHECK, not by the beacon).
set "HEADROOM_BEACON=off"
set "HEADROOM_UPDATE_CHECK=off"
set "HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS=120"

rem --- make sure the pinned dirs exist --------------------------------------
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%" 2>nul
if not exist "%UV_TOOL_DIR%" mkdir "%UV_TOOL_DIR%" 2>nul
if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%" 2>nul
if not exist "%TIKTOKEN_CACHE_DIR%" mkdir "%TIKTOKEN_CACHE_DIR%" 2>nul
if not exist "%HEADROOM_WORKSPACE_DIR%" mkdir "%HEADROOM_WORKSPACE_DIR%" 2>nul

rem --- hand over to uvx; stdio is passed straight through --------------------
uvx --from "headroom-ai[mcp]" headroom mcp serve
exit /b %ERRORLEVEL%
