# DeepSeek-Harness-Headroom-Plugin

![bundle](https://img.shields.io/badge/bundle-v1.0.0-CB3837?logo=npm&logoColor=white)
![license](https://img.shields.io/badge/license-Apache--2.0-brightgreen)
![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![DeepSeek Harness](https://img.shields.io/badge/DeepSeek_Harness-plugin-4D6BFE?logo=deepseek&logoColor=white)

Bring [Headroom](https://github.com/headroomlabs-ai/headroom) — a local-first
context-compression toolkit — to the **DeepSeek Harness** as a native plugin.

After installing, your DSH can compress large blobs on demand and retrieve the
originals byte-for-byte, and any provider you point at the bundled proxy gets
compressed transparently — no changes to your prompts.

**[中文文档](README.zh.md)**

---

## What you get

Three native tools, exposed through Headroom's own MCP server:

| Tool | What it does |
| --- | --- |
| `mcp__headroom__headroom_compress` | Compress a large blob (tool output, file, log, search result) → compressed text + a retrieval hash |
| `mcp__headroom__headroom_retrieve` | Fetch the byte-identical original back by that hash |
| `mcp__headroom__headroom_stats` | Session stats: compressions, tokens saved, estimated cost |

Two ways to use them, and they are independent:

**1. On-demand tools — works with any provider.** The model decides when to call
them. Nothing about your traffic changes; you gain compression only when the agent
chooses to use it.

**2. Transparent compression — an HTTP proxy.** Every byte of traffic through a
repointed provider is compressed automatically, whether or not the model asks.
Measured on a 500-row tool result:

```
before    : 27665 tokens
after     : 18812 tokens
saved     :  8853 tokens  (32.0%)
transform : router:smart_crusher:0.54
```

The FATAL row (id 67) survived compression, and the model still answered with it.
Compression is **reversible**: originals live in a local store and come back
byte-identical, so nothing is lost — it is only deferred. Byte-identity is a
property of the *store*, not of the compacted text: what the model reads inline is
lossy, and the original is recovered by asking for it.

## Install

**Prerequisites:** a working DSH profile, and `uv`/`uvx` on `PATH`.

If `uvx --version` does not print a version yet, install `uv` first — it is the one
prerequisite, and the same command works on Windows, macOS and Linux:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# or, if you already have Python and pip
pip install uv
```

Reopen the terminal afterwards and check `uvx --version`. Nothing else is
required: `uvx` fetches Headroom and all of its Python dependencies by itself,
so there is no Python environment to create and no package to build.

Clone this repository anywhere you like — the MCP row starts `uvx` from `PATH`, so
it does not care where the bundle is installed; only the `install_bundle` step
needs an absolute path to locate the bundle.

```bash
git clone <this-repo> dsh-headroom
cd dsh-headroom
```

Nothing needs building. Headroom itself is fetched by `uvx` on first use, and the
proxy environment is created on demand by its launcher.

### Step 1 — nothing to configure

The shipped patch is zero-config — it pulls up the upstream `headroom mcp serve`
directly via `uvx` on `PATH`, so there is nothing to edit:

```yaml
command: uvx
args:
  - '--from'
  - 'headroom-ai[mcp]'
  - 'headroom'
  - 'mcp'
  - 'serve'
env:
  HEADROOM_BEACON: 'off'
  HEADROOM_UPDATE_CHECK: 'off'
  HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS: '120'
failOnStartupError: true
```

`command` has no directory component, and the stdio transport resolves it through
the `PATH` (`cross-spawn`), so neither the install location nor the Host's working
directory matters any more — which is exactly what makes a config-only patch
portable. `uvx` is the same name on Windows (`uvx.exe`), macOS, and Linux, so the
MCP row has no `.cmd`/`.sh` platform split. `args` reaches the child as the argv
verbatim, so `headroom-ai[mcp]` needs no quoting.

### Step 2 — install the bundle

```
plugin_manager  action=install_bundle  target=<absolute-path-to-this-repo>\plugin
```

That runs `pnpm` in your profile, links `@local/dsh-headroom` into
`~/.dsh/profiles/<profile>/node_modules`, and applies the patch to the live
profile. Success reports `application: applied` with empty `warnings`. Restart
DSH if your profile is not the live one. Once installed, the `headroom-mcp` row is
`active` and the three `mcp__headroom__*` tools are immediately usable — no need
to launch the Harness from any particular directory.

> This one path is unavoidably absolute — `install_bundle` is told *where the
> bundle is* by you. Everything after it is relative.

### Step 3 — remove it again

```
plugin_manager  action=remove_bundle  target=@local/dsh-headroom
```

### A note on environment variables

DSH scrubs the environment it hands to MCP children: any name matching
`/KEY|PASSWORD|SECRET|TOKEN/i` is dropped, as is any name beginning with `DSH_`
(`dsh-subprocess/lib/index.js:32,52`). This bundle's variables are all named
`HEADROOM_*`, so they pass through untouched — but it is worth knowing before you
add a credential-style name of your own.

`HEADROOM_DSH_WORKSPACE` overrides the launchers' workspace detection. You only
need it if you invoke a launcher from a relocated or symlinked location.

## Verifying the install

[`plugin/verify/verify_headroom.py`](plugin/verify/verify_headroom.py) proves the
whole chain end-to-end — the sanitizer, model discovery, a real SSE stream, and
an actual compression:

```
.proxy-venv/Scripts/python.exe plugin/verify/verify_headroom.py \
    --credentials ~/.dsh/.credentials.yaml
```

```
==========================================================================
summary
==========================================================================
  header     PASS
  discovery  PASS
  stream     PASS
  compress   PASS

OVERALL: PASS
```

Each check prints its own `RESULT: PASS` line with the numbers it observed, so a
failing run says which stage failed and why. `--only header` runs the offline
check that needs no key and no network. Exit code is non-zero on failure, so it
drops straight into CI.

[`plugin/README.md`](plugin/README.md) additionally documents the MCP handshake
check and the other manual verification steps.

## Transparent compression (the proxy)

Start the proxy — **nothing auto-starts it**, and it needs to be told where to
forward:

```powershell
plugin\bin\headroom-proxy.cmd https://your-provider.example/v1
```

There is deliberately **no built-in upstream**. A proxy that silently forwarded to
an endpoint you did not choose would send your content and your API key somewhere
unexpected, so the launcher exits with an error instead of guessing. Give it an
argument, `HEADROOM_UPSTREAM_URL`, or a pre-existing `OPENAI_TARGET_API_URL`.

Then point a provider's `baseURL` at it:

```yaml
# your profile's cordis.patch.yml, inside an llm-pi-ai provider
baseURL: http://127.0.0.1:8787/v1
```

The proxy forwards to `OPENAI_TARGET_API_URL` and passes the client's
`Authorization` header through unchanged, so the provider key stays whatever DSH
already sends — nothing is duplicated, intercepted, or stored. Per-request token
accounting appears in the response headers (`x-headroom-tokens-before/after/saved`,
`x-headroom-transforms`), and running totals land in
`.headroom/savings_events.jsonl`.

Three settings matter, and all three were necessary here:

| Setting | Value | Why |
| --- | --- | --- |
| `--mode` | `token` | `cache` mode freezes prior turns to protect the provider's prefix cache; a frozen payload is never compressed, which measured **zero** savings. `token` mode does not freeze. Both modes behave identically on content neither one freezes. |
| `HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS` | `0` | The HF tokenizer download never completes here, so every request stalled for the full timeout (~10s). Disabling the fetch cut `opt_ms` from ~10000ms to 26–66ms. |
| A patched venv | via `bin/setup-proxy-venv.cmd` | `uvx` builds an ephemeral env each run, so a source patch would vanish. |

## The one upstream bug this needed

Headroom writes the caller's model id into a response header:

```python
headers["x-headroom-model"] = model
```

DSH's model picker yields the id `deepseek-v4.1-flash ` — with a **trailing
space**. HTTP header values may not carry that, so `h11` (uvicorn's HTTP/1.1
stack) rejected the response *after* upstream had already answered 200:

```
h11._util.LocalProtocolError: Illegal header value b'deepseek-v4.1-flash '
→ client saw: httpx.RemoteProtocolError: Server disconnected without sending a response
```

The symptom was that **every streaming request failed with no explanation** from
the client side.

[`plugin/patch_headroom_model_header.py`](plugin/patch_headroom_model_header.py)
adds `header_safe_model()` to `headroom/proxy/cost.py` — mirroring the existing
`header_safe_transforms` — and routes all five `x-headroom-model` assignment sites
through it. It strips surrounding whitespace, replaces control characters, and
omits the header entirely when there is no usable value.

It touches **only this metering header** — never routing, never the request body —
so it cannot change what the model sees. The trailing space is harmless upstream
(both spellings returned HTTP 200), so sanitizing loses no information.

The patch is applied to the **installed package**, not to a checkout, and
`bin/setup-proxy-venv.cmd` runs it automatically every time the proxy starts — so
a fresh clone patches itself with no manual step. Nothing here depends on the
Headroom source tree:

```
[setup] applying header-safety patch
  proxy/cost.py                 -> patched
  proxy/handlers/streaming.py   -> patched (1 site(s))
  proxy/handlers/openai.py      -> patched (1 site(s))
  proxy/handlers/anthropic.py   -> patched (1 site(s))
  proxy/handlers/gemini.py      -> patched (2 site(s))
  syntax OK for all 5 files
```

The script is idempotent, reports `patched` / `already` per file, and supports
`--check` to verify without writing. It is applied automatically by
`bin/setup-proxy-venv.cmd` on every proxy launch, so an upgraded or rebuilt venv
cannot silently lose the fix.

## Layout

| Path | Role |
| --- | --- |
| [`plugin/`](plugin/) | **The installable DSH bundle** — manifest, Cordis patch, optional launchers |
| [`plugin/cordis.patch.yml`](plugin/cordis.patch.yml) | Inserts the `headroom-mcp` row (an `@deepseek-ai/dsh-mcp-client` stdio entry that starts the upstream `headroom mcp serve` via `uvx`) |
| [`plugin/bin/headroom-mcp.cmd`](plugin/bin/headroom-mcp.cmd) | Optional MCP convenience wrapper (Windows), for **manual testing** only — the bundle uses `uvx` directly and does not invoke it; [`headroom-mcp.sh`](plugin/bin/headroom-mcp.sh) is the POSIX equivalent |
| [`plugin/bin/headroom-proxy.cmd`](plugin/bin/headroom-proxy.cmd) | Proxy launcher — token mode, no auto-start |
| [`plugin/bin/setup-proxy-venv.cmd`](plugin/bin/setup-proxy-venv.cmd) | Creates `.proxy-venv` and applies the header patch; idempotent |
| [`plugin/patch_headroom_model_header.py`](plugin/patch_headroom_model_header.py) | The header-safety source patch; `--check` verifies without writing |
| [`plugin/verify/verify_headroom.py`](plugin/verify/verify_headroom.py) | End-to-end verifier; exits non-zero on failure |
| [`plugin/upstream/dsh.py`](plugin/upstream/dsh.py) | **New upstream registrar**: teaches `headroom mcp install` to write DSH profile config |
| [`plugin/patch_headroom_mcp_registry.py`](plugin/patch_headroom_mcp_registry.py) | Installs that registrar into any Headroom tree; idempotent, `--check` supported |

> The upstream Headroom source is **not** vendored here. It is a 68 MB tree of
> third-party code that nothing at runtime reads, so this repository carries only
> our own code plus the two patches that modify upstream. Point the patch scripts
> at whichever Headroom tree you have — the installed package in `.proxy-venv`,
> or your own checkout.

### Two integration paths

Both are delivered, and they are complementary rather than redundant:

1. **The bundle (what you install).** `plugin/` registers Headroom's MCP server
   with DSH's `dsh-mcp-client` row. Config only — no Host or Client JavaScript
   runs.
2. **The upstream registrar (a source patch).** [`plugin/upstream/dsh.py`](plugin/upstream/dsh.py)
   adds DSH to Headroom's own `mcp_registry`, so Headroom can install *itself*
   into DSH the way it already does for Claude Code, Codex, and OpenCode. This is
   the right long-term home for the integration; the bundle exists because a
   config-only install needs no upstream release.

`patch_headroom_mcp_registry.py` applies the registrar: it drops in `dsh.py` and
adds the one-line import plus the one-line fleet entry to `__init__.py` and
`install.py`. It is idempotent and verified to reproduce a working registrar
against released 0.41.0:

```
python plugin/patch_headroom_mcp_registry.py --target .proxy-venv/Lib/site-packages/headroom
```

The install state you want to see:

```
  mcp_registry/dsh.py                -> patched
  mcp_registry/__init__.py           -> patched
  mcp_registry/install.py            -> patched
  dsh.py parses; registered in __init__.py and install.py
registrar integration OK
```

## Honest limits

We would rather you know these up front than discover them in production.

- **Only repointed providers are compressed.** The proxy is inserted by
  `baseURL`, so a plugin that owns its own adapter and hardcodes its endpoint
  cannot be covered. `opencode2dsh` is exactly that case: its config schema has no
  `baseURL`/`zenBaseUrl` key, it reads no environment variables, and its
  `zenBaseUrl` constructor option is never populated from config — so it always
  targets `https://opencode.ai/zen`.
- **There is no "auto-follow the user's model" mode.** The obvious seam —
  `ctx.llm`'s `llm/stream` waterfall — cannot rewrite routing: a loop-built
  request "arrives deep-frozen (mutation throws)" by contract, so a listener may
  read it but never repoint `provider`/`model`. Provider-level `baseURL`
  redirection is the only supported insertion point. `agent-default-model` also
  accepts just three static fields, with no `auto` or `follow` value. Provider
  selection stays per-session, which is the intended mechanism.
- **The newest user message is never compressed.** Headroom protects
  `last_user_item_idx` by design, so a request whose bulk sits in the final user
  turn saves nothing (`router:protected:user_message`). Savings appear when the
  bulk is in tool results or older turns.
- **The biggest tool results are deliberately not compressed.** Headroom protects
  `Read`, `Glob`, `Grep`, `Write`, `Edit`, `WebFetch`, `WebSearch` and
  `headroom_retrieve` by name (plus lowercase variants), so file reads and search
  output — often the bulk of a coding session — pass through untouched. This is a
  correctness choice, not an oversight: lossy compression on raw file bytes the
  model is patching against, or on a retrieved original, would corrupt work. What
  *does* compress is bulky tool output from non-protected tools: database rows,
  API responses, and large JSON in custom tool results — verified at 33.7%
  (9227 tokens) on a 500-row payload under a custom tool name.
- **Compression depends on structure, not size.** A 400-row JSON array saved
  41.2% (`router:smart_crusher:0.47`), while the same rows as JSON Lines saved
  only 5.8% — array structure is what SmartCrusher exploits. `headroom_compress`
  reports the `transforms` it applied, so an unexpectedly small saving is visible
  rather than silent.
- **The proxy must be running** for repointed providers; they fail outright rather
  than falling back. Uncovered providers are unaffected, so a stopped proxy does
  not break your normal sessions.
- **First MCP launch is slow.** `uvx` installs `headroom-ai[mcp]` and its
  dependencies, and needs network access. Later launches use the cache.
- **Prose needs the ML model, and it warms up slowly.** Plain-text compression runs
  through Headroom's Kompress backend, which downloads an ONNX model (roughly 260 MB)
  on first use and then takes about two to three minutes to warm up on a cold start.
  Until it reports ready, prose passes through uncompressed — structured content
  (JSON, logs, code) is compressed the whole time. Check `/debug/warmup` on the
  proxy for `kompress: loaded`. Note also that the two paths differ here: the proxy
  environment ships the ONNX backend, while the MCP row installs `headroom-ai[mcp]`
  only, so `headroom_compress` compresses structured content and returns prose
  unchanged.
- **This is not a re-implementation.** Compression runs in Headroom's own process,
  using its published code. The only changes made for this integration are the
  header patch and the registrar addition, both in `plugin/`.
- **No telemetry, and the update check is off.** The launchers disable both
  outbound paths: `HEADROOM_BEACON=off` for the anonymous, content-free session
  summary that is **on by default** upstream, and `HEADROOM_UPDATE_CHECK=off` for
  the once-a-day PyPI version probe, which is gated separately and would otherwise
  still fire. The local-only `HEADROOM_TELEMETRY` switch is off by default and
  never leaves the machine. That said, Headroom is third-party code running
  locally with your content — read it before trusting it with anything sensitive.

## Environment notes

Every writable directory is pinned inside the workspace, because a sandboxed
Harness cannot write `~/.headroom`, `~/.cache/uv`, or uv's tool directories. Each
of these was an actual failure encountered during development:

| Variable | Value | Prevents |
| --- | --- | --- |
| `UV_CACHE_DIR` / `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` | `<workspace>/.uv-*` | uv cache and shim permission errors |
| `TIKTOKEN_CACHE_DIR` | `<workspace>/.tiktoken-cache` | a stalled tokenizer vocab download |
| `HEADROOM_WORKSPACE_DIR` | `<workspace>/.headroom` | `[WinError 5]` writing `~/.headroom` (the CCR store) |
| `HEADROOM_BEACON` | `off` | the anonymous usage beacon |
| `HEADROOM_UPDATE_CHECK` | `off` | the daily PyPI version probe (a separate egress path) |
| `HEADROOM_DSH_WORKSPACE` | *(optional)* | overrides workspace-root detection |

`.uv-cache`, `.uv-tools`, `.uv-bin`, `.tiktoken-cache`, `.headroom`, and
`.proxy-venv` hold downloaded packages and runtime state. They are safe to delete
to reclaim disk space; the next launch reinstalls.

## License

This project is **Apache-2.0** — see [LICENSE](LICENSE). It is an integration
around Headroom, which is itself Apache-2.0; third-party attribution for the
components Headroom builds on is carried in [NOTICE](NOTICE).
