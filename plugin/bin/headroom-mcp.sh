#!/usr/bin/env sh
# =============================================================================
#  Headroom MCP server launcher (POSIX)
#
#  Starts `headroom mcp serve` over stdio for the DSH mcp-client plugin.
#  All uv + Headroom state is pinned inside the workspace so that a sandboxed
#  harness (workspace-write) can read/write everything it needs.
#
#  Workspace root resolution order:
#    1. $HEADROOM_DSH_WORKSPACE  (explicit override)
#    2. two levels up from this script's directory  (plugin/bin -> workspace)
# =============================================================================
set -eu

if [ -n "${HEADROOM_DSH_WORKSPACE:-}" ]; then
  WS="$HEADROOM_DSH_WORKSPACE"
else
  SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
  WS=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
fi

# --- pin every cache/tool/state directory inside the workspace ---------------
UV_CACHE_DIR="$WS/.uv-cache"
UV_TOOL_DIR="$WS/.uv-tools"
UV_TOOL_BIN_DIR="$WS/.uv-bin"
TIKTOKEN_CACHE_DIR="$WS/.tiktoken-cache"
HEADROOM_WORKSPACE_DIR="$WS/.headroom"

# --- local-first: no telemetry, no network surprises ------------------------
# Two independent outbound paths: the beacon, and the daily PyPI update probe
# (gated by HEADROOM_UPDATE_CHECK, not by the beacon switch).
HEADROOM_BEACON=off
HEADROOM_UPDATE_CHECK=off
HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS=120

export UV_CACHE_DIR UV_TOOL_DIR UV_TOOL_BIN_DIR
export TIKTOKEN_CACHE_DIR HEADROOM_WORKSPACE_DIR
export HEADROOM_BEACON HEADROOM_UPDATE_CHECK HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS

mkdir -p "$UV_CACHE_DIR" "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" \
         "$TIKTOKEN_CACHE_DIR" "$HEADROOM_WORKSPACE_DIR" 2>/dev/null || true

# --- hand over to uvx; stdio is passed straight through ---------------------
exec uvx --from "headroom-ai[mcp]" headroom mcp serve
