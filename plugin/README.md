# @local/dsh-headroom

A configuration-only Cordis bundle that registers **Headroom's MCP server** into
the DeepSeek Harness.

It adds one row to the Harness plugin list — an `@deepseek-ai/dsh-mcp-client`
entry that spawns Headroom over stdio — so the agent can compress large content
and retrieve the original on demand, without leaving the conversation.

**[中文文档](README.zh.md)** · [Top-level docs](../README.md)

- Package: `@local/dsh-headroom` v1.0.0
- Bundle patch: [`cordis.patch.yml`](cordis.patch.yml)
- MCP launcher: [`bin/headroom-mcp.cmd`](bin/headroom-mcp.cmd) (Windows) / [`bin/headroom-mcp.sh`](bin/headroom-mcp.sh) (POSIX)
- Proxy launcher: [`bin/headroom-proxy.cmd`](bin/headroom-proxy.cmd) + [`bin/setup-proxy-venv.cmd`](bin/setup-proxy-venv.cmd)

The bundle is **inert config** — no Host or Client JavaScript runs. Everything it
does is spawn Headroom's own executable.

---

## What it does

Headroom is a local-first context-compression toolkit. This bundle exposes its MCP
server to the agent as three on-demand tools:

| Tool | Purpose |
| --- | --- |
| `mcp__headroom__headroom_compress` | Compress a large blob (tool output, file contents, search results, logs) and return compressed text plus a retrieval hash. |
| `mcp__headroom__headroom_retrieve` | Fetch the original uncompressed content back by hash. |
| `mcp__headroom__headroom_stats` | Report session statistics: compressions, tokens saved, estimated cost savings, recent events. |

The agent decides when to call them. Nothing happens automatically — which also
means nothing about your existing traffic changes.

Compression is **reversible**: originals are stored locally in Headroom's CCR store
and come back byte-identical, so this defers context rather than discarding it.
Byte-identity belongs to the store, not to the compacted text: the inline copy is
lossy and the original comes back only when retrieved.

## Transparent compression (the proxy)

Start the proxy — **nothing auto-starts it**, and it needs to be told where to
forward:

```powershell
plugin\bin\headroom-proxy.cmd https://your-provider.example/v1
```

There is deliberately **no built-in upstream**. A proxy that silently forwarded to
an endpoint you did not choose would send your content and your API key somewhere
unexpected, so the launcher exits with an error instead of guessing. Give it an
argument, `HEADROOM_UPSTREAM_URL`, or a pre-existing `OPENAI_TARGET_API_URL` —
the same base URL your provider would use directly.

Then point a provider's `baseURL` at it:

```yaml
# your profile's cordis.patch.yml, inside an llm-pi-ai provider
baseURL: http://127.0.0.1:8787/v1
```

The proxy forwards to `OPENAI_TARGET_API_URL` and passes the client
`Authorization` header through unchanged, so the provider key is whatever DSH
already sends — nothing is duplicated or stored.

Measured on a 500-row JSON tool result: **27665 → 18812 tokens, 32.0% saved**,
transform `router:smart_crusher:0.54`, with the FATAL row still present and named
correctly by the model. Per-request token accounting is in the response headers
(`x-headroom-tokens-before/after/saved`, `x-headroom-transforms`); running totals
land in `.headroom/savings_events.jsonl`.

### Three settings the proxy needs

| Setting | Value | Why |
| --- | --- | --- |
| `--mode` | `token` | `cache` mode freezes prior turns to protect the provider prefix cache; a frozen payload is never compressed, which measured **zero** savings on a 500-row tool result. `token` mode does not freeze. |
| `HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS` | `0` | The HF tokenizer download cannot complete here, so every request used to stall for the full timeout (~10s). Disabling the fetch cut `opt_ms` to 26–66ms. |
| patched venv | via `setup-proxy-venv.cmd` | `uvx` rebuilds an ephemeral env, so a source patch would vanish. See the header-safety patch in the [top-level README](../README.md#the-one-upstream-bug-this-needed). |

### The proxy is not auto-started

Nothing launches it for you, and a provider pointed at a stopped proxy fails
outright instead of falling back. Start it as a managed background job and keep it
running for as long as you want compression.

Uncovered providers are unaffected by a stopped proxy, so this does not put your
normal sessions at risk.

## Why the launcher exists

The MCP launcher installs Headroom on demand via `uvx`. Under a sandboxed Harness
(workspace-write) the default uv and Headroom state directories live outside the
workspace and are not writable, so the launcher pins all of them inside the
workspace before exec'ing `uvx`:

| Variable | Value | Why |
| --- | --- | --- |
| `UV_CACHE_DIR` | `<workspace>/.uv-cache` | uv's package cache |
| `UV_TOOL_DIR` | `<workspace>/.uv-tools` | uv tool environments |
| `UV_TOOL_BIN_DIR` | `<workspace>/.uv-bin` | uv tool shims |
| `TIKTOKEN_CACHE_DIR` | `<workspace>/.tiktoken-cache` | prevents a stalled tiktoken vocab download |
| `HEADROOM_WORKSPACE_DIR` | `<workspace>/.headroom` | Headroom cannot write `~/.headroom` under a sandbox |
| `HEADROOM_BEACON` | `off` | disables the anonymous usage beacon (local-first, no telemetry) |
| `HEADROOM_UPDATE_CHECK` | `off` | disables the daily PyPI version probe — gated separately from the beacon |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | bounds vocab-load stalls |

The workspace root is resolved once, at the top of each launcher:

1. `HEADROOM_DSH_WORKSPACE` env var, if set; otherwise
2. two levels up from the script's own directory (`plugin/bin` → workspace root).

So the bundle can be relocated, and it works from any working directory once the
patch's `cwd` expression resolves (see [Relocating the bundle](#relocating-the-bundle)).

The final command is:

```
uvx --from "headroom-ai[mcp]" headroom mcp serve
```

### Overrides

Every value above is a default you can replace by setting the variable before
launching. These are read but not listed in the table, because you rarely need
them:

| Variable | Default | Effect |
| --- | --- | --- |
| `HEADROOM_DSH_WORKSPACE` | two levels above the script | Workspace root every other path is derived from |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | Bounds the MCP server's vocab-load stall |
| `HEADROOM_MODE` | `token` | Proxy compression mode (`token` or `cache`) |
| `HEADROOM_PORT` | `8787` | Proxy listen port |
| `HEADROOM_UPSTREAM_URL` | *(none — required)* | Proxy upstream; argument 1 wins over it |
| `HEADROOM_PROXY_VENV` | `<workspace>/.proxy-venv` | Where the patched proxy environment lives |
| `HEADROOM_PYTHON` | `3.12` | Interpreter version `setup-proxy-venv.cmd` requests |
| `HEADROOM_PROXY_EXTRAS` | `proxy` | Headroom extras installed into the venv |

## Install

The parent of this folder is the repository root; clone it and work from there.
Ask the Harness agent to install `plugin/` as a local bundle — it calls the
`plugin_manager` tool with `action: install_bundle` and this folder as the target:

```
plugin_manager  action=install_bundle  target=<path-to-repo>\plugin
```

That is the supported path and the one used here. It runs pnpm in the profile,
links `@local/dsh-headroom` into `~/.dsh/profiles/<profile>/node_modules`, and
applies the patch to the live profile (a live profile needs no restart). A
successful result reports `application: applied` with empty `warnings`.

**Before installing, edit `command` in [`cordis.patch.yml`](cordis.patch.yml)** —
see [Relocating the bundle](#relocating-the-bundle).

Do not hand-edit the profile's `package.json` or `cordis.patch.yml`; the bundle
owns its own patch file and the manager owns the profile.

### Relocating the bundle

An MCP `command` is spawned **verbatim** by the SDK with `shell: false`
(`@modelcontextprotocol/client/dist/stdio.mjs`), and `dsh-mcp-client`'s config
schema declares it as a plain `z.string().required()` with no path resolution —
the module does not import `path` at all. The Loader's relative-path anchoring
covers a row's `name` (its `anchorInsertedPluginNames` pass rewrites `entry.name`
only), **not** a plugin's own config values. So a relative `command` is never
resolved against the patch file.

It *is* resolved against `cwd`, however — and `dsh-mcp-client` accepts a `cwd`
key (`lib/index.js:786`, default `""`) which it forwards to the SDK's stdio
transport (`:44`). That is what makes a config-only patch portable:

```yaml
cwd: !!js process.env.DSH_HEADROOM_ROOT || process.cwd()
command: plugin\bin\headroom-mcp.cmd
```

Start the Harness from the repository root and the fallback is already correct;
start it anywhere else and `DSH_HEADROOM_ROOT` supplies the root. The launchers
hardcode nothing either — each resolves its own workspace root from
`HEADROOM_DSH_WORKSPACE`, falling back to two directories above its own location.

`!!js` is the Cordis entry-list dialect, evaluated in the Host at activation via
`with (ctx) { return eval(expr) }`. That scope exposes Node globals such as
`process`, but **not** `__dirname`, `__filename`, `require`, or `module` — so a
repository-relative path cannot be derived automatically; it must come from the
environment or the working directory.

Note also that DSH scrubs any environment name matching
`/KEY|PASSWORD|SECRET|TOKEN/i` — and every `DSH_*` name — before handing it to an
MCP child (`dsh-subprocess/lib/index.js:32,52`). This bundle's `HEADROOM_*` and
`DSH_HEADROOM_ROOT` names: the former pass through untouched; the latter is read
by the Loader *before* that scrub, since it is evaluated in the Host, not in the
child. Prefer `HEADROOM_DSH_WORKSPACE` for anything the launcher itself reads.

## Verify

Four independent checks, cheapest first.

### 1. The patch parses and has the expected shape

```powershell
node -e "const{createRequire}=require('module');const r=createRequire(process.env.DSH_CHECKOUT+'/node_modules/');const y=r('yaml');const d=y.parse(require('fs').readFileSync('plugin/cordis.patch.yml','utf8'));console.log(JSON.stringify(d,null,2))"
```

Expect a top-level array with one `insert` row whose `config.serverName` is
`headroom` and whose `config.command` points at the launcher.

### 2. The MCP server answers the handshake

Write the three JSON-RPC lines to a file, then pipe it in. PowerShell pipelines are
required — a piped Node `child_process.spawn` hits the sandbox's EPERM boundary.

```powershell
$req = @(
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"p","version":"1"}}}',
  '{"jsonrpc":"2.0","method":"notifications/initialized"}',
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
) -join "`n"
$req | Out-File -Encoding ascii -NoNewline .req.jsonl
Get-Content -Raw .req.jsonl | & plugin\bin\headroom-mcp.cmd 2>$null | Out-File -Encoding utf8 .out.txt
Get-Content .out.txt
```

`initialize` should report `serverInfo.name = "headroom"`. A short-lived pipeline
may return only the `initialize` response, because stdin closes before the async
`tools/list` resolves — that is a shell artifact, not a launcher bug. To see the
tool list reliably, keep stdin open until the `id:2` response arrives:

```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/d /s /c "<path-to-repo>\plugin\bin\headroom-mcp.cmd"'
$psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)
$p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"p","version":"1"}}}')
$p.StandardInput.WriteLine('{"jsonrpc":"2.0","method":"notifications/initialized"}'); $p.StandardInput.Flush()
$p.StandardOutput.ReadLine()
Start-Sleep -Milliseconds 1500
$p.StandardInput.WriteLine('{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'); $p.StandardInput.Flush()
$p.StandardOutput.ReadLine()
$p.StandardInput.Close(); $p.WaitForExit(30000)
```

Expect a `tools` array naming `headroom_compress`, `headroom_retrieve`, and
`headroom_stats`.

### 3. In the Harness

After installing, `plugin_manager` `list_plugins` should show the `headroom-mcp` row
active, and the agent should see the three `mcp__headroom__*` tools.

### 4. End-to-end verifier

[`verify/verify_headroom.py`](verify/verify_headroom.py) checks the whole chain
against a running proxy:

```powershell
plugin\bin\headroom-proxy.cmd          # in another window, or as a background job
.proxy-venv\Scripts\python.exe plugin\verify\verify_headroom.py `
    --credentials "$env:USERPROFILE\.dsh\.credentials.yaml"
```

It runs four checks and prints `OVERALL: PASS`, exiting non-zero on any failure:

| Check | Proves |
| --- | --- |
| `header` | h11 accepts every sanitized `x-headroom-model` value (and shows the raw value failing) |
| `discovery` | `GET /v1/models` passes through, so the provider picker works |
| `stream` | a real SSE completion survives the round trip with a trailing-space model id |
| `compress` | a 500-row tool result shrinks, and the FATAL row survives |

Use `--only header` for the offline check that needs no key and no network. The key
comes from `HEADROOM_TEST_API_KEY`, or from the credentials file via
`--credentials` / `--credential-ref`.

## Uninstall

```
plugin_manager  action=remove_bundle  target=@local/dsh-headroom
```

Then delete the workspace cache dirs if you want the disk space back:
`.uv-cache`, `.uv-tools`, `.uv-bin`, `.tiktoken-cache`, `.headroom`, `.proxy-venv`.

## Known cosmetic warning

`headroom_compress` and `headroom_stats` include this in their result:

```
"proxy": {"url": "http://127.0.0.1:8787", "status": "unreachable", ...},
"warning": "Configured proxy http://127.0.0.1:8787 is unreachable ..."
```

This is **expected and harmless**. Headroom probes the optional local HTTP proxy on
every call and reports it as unreachable when the proxy is not running. Standalone
mode — compression in-process, originals in the local CCR store — needs no proxy at
all, and `headroom_retrieve` is served from `"source": "local"`. To silence the
probe, point `HEADROOM_PROXY_URL` at a running proxy via the launcher's `env`.

## Limits

- **Two modes, different scopes.** The MCP half exposes on-demand tools the agent
  must choose to call; the proxy half compresses transparently, but only for
  providers you repoint at it. `bin/headroom-proxy.cmd` is the proxy launcher —
  nothing starts it for you, and it is not part of the MCP row.
- **Coverage depends on the provider.** A provider opts in by setting
  `baseURL: http://127.0.0.1:8787/v1`. A plugin that owns its own adapter (for
  example `opencode2dsh`, which hardcodes `opencode.ai/zen`) cannot be repointed
  and stays uncompressed.
- **The newest user message is never compressed.** Headroom protects it by design,
  so a request whose bulk is in the final user turn saves nothing.
- **Protected tools are never compressed.** `Read`, `Glob`, `Grep`, `Write`,
  `Edit`, `WebFetch`, `WebSearch` and `headroom_retrieve` (plus lowercase
  variants) are excluded by name, so file reads and search output pass through
  untouched — a correctness choice, since lossy compression on raw file bytes or
  on a retrieved original would corrupt work. The verifier's `compress` check
  deliberately uses a custom tool name (`query_logs`) for this reason; a synthetic
  `read` result would report 0% and look like a failure. Bulky non-protected tool
  output (database rows, API responses) is what actually shrinks.
- **Repetitive structure is what compresses.** A 400-row JSON array saved 41.2%
  (`router:smart_crusher:0.47`), while the same rows as JSON Lines saved only
  5.8% — SmartCrusher exploits array structure. `headroom_compress` reports the
  `transforms` it applied, so an unexpectedly small saving is visible rather than
  silent.
- **The proxy must be running.** A provider pointed at a stopped proxy fails
  outright rather than falling back to the direct upstream.
- **First run is slow.** `uvx` installs `headroom-ai[mcp]` and its dependencies on
  first launch. Expect a delay and network access; subsequent runs are cached.
- **`uvx` must be on `PATH`.** The launcher calls `uvx` by name.
- **Windows launcher is `.cmd`.** It cannot be spawned directly without a shell;
  `dsh-mcp-client` invoking it as `command` goes through `cmd.exe` on Windows. The
  `.sh` launcher is the POSIX equivalent.
- **The patch resolves the launcher via `cwd`.** It works as shipped when you start
  the Harness from the repository root; otherwise set `DSH_HEADROOM_ROOT` to that
  root so the `!!js` expression finds it.
- **No telemetry, and the update check is off** (`HEADROOM_BEACON=off` plus
  `HEADROOM_UPDATE_CHECK=off`, two separately gated paths), but the compression
  library itself is third-party code running locally with your content.
