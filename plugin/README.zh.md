# @local/dsh-headroom

一个纯配置的 Cordis bundle，把 **Headroom 的 MCP server** 注册进 DeepSeek Harness。

它向 Harness 插件列表追加一行 —— 一个通过 stdio 拉起 Headroom 的 `@deepseek-ai/dsh-mcp-client` 条目 —— 于是 agent 无需离开对话，就能按需压缩大块内容并取回原文。

**[English](README.md)** · [顶层文档](../README.zh.md)

- 包名：`@local/dsh-headroom` v1.0.1
- Bundle 补丁：[`cordis.patch.yml`](cordis.patch.yml)
- 可选的 MCP 便捷包装（仅供手动测试）：[`bin/headroom-mcp.cmd`](bin/headroom-mcp.cmd)（Windows）/ [`bin/headroom-mcp.sh`](bin/headroom-mcp.sh)（POSIX）
- 代理启动器：[`bin/headroom-proxy.cmd`](bin/headroom-proxy.cmd) + [`bin/setup-proxy-venv.cmd`](bin/setup-proxy-venv.cmd)

本 bundle 是**惰性配置** —— 不运行任何 Host 或 Client JavaScript。它做的全部事情就是拉起 Headroom 自己的可执行文件。

---

## 它做什么

Headroom 是一个本地优先的上下文压缩工具包。本 bundle 把它的 MCP server 以三个按需工具的形式暴露给 agent：

| 工具 | 用途 |
| --- | --- |
| `mcp__headroom__headroom_compress` | 压缩大块内容（工具输出、文件内容、搜索结果、日志），返回压缩后文本及一个取回哈希。 |
| `mcp__headroom__headroom_retrieve` | 用哈希取回未压缩的原文。 |
| `mcp__headroom__headroom_stats` | 报告会话统计：压缩次数、节省 token、预估成本节省、近期事件。 |

由 agent 决定何时调用它们。没有任何自动行为 —— 这也意味着你现有的流量不会发生任何变化。

压缩是**可逆的**：原文存放在 Headroom 的本地 CCR 存储中，取回时逐字节一致，所以这是把上下文延后，而不是丢弃。逐字节一致性属于存储，而非压缩后的文本：内联的那份是有损的，只有取回时才会拿回原文。

## 透明压缩（代理）

运行 Headroom 的 HTTP 代理 —— **没有任何东西会自动启动它**，而且它需要被告知转发到哪里：

```powershell
plugin\bin\headroom-proxy.cmd https://your-provider.example/v1
```

这里**有意不设内置上游**。一个会静默转发到你并未选择的端点的代理，会把你的内容和 API key 发往意料之外的地方，因此启动器会直接报错退出而不是猜测。请通过参数、`HEADROOM_UPSTREAM_URL`，或已存在的 `OPENAI_TARGET_API_URL` 提供它 —— 就是你 provider 直连时会用的那个 base URL。

然后把某个 provider 的 `baseURL` 指过来：

```yaml
# 你的 profile cordis.patch.yml，位于某个 llm-pi-ai provider 内
baseURL: http://127.0.0.1:8787/v1
```

代理会转发到 `OPENAI_TARGET_API_URL`，并原样透传客户端的 `Authorization` 头，因此 provider 密钥始终是 DSH 自己发送的那个 —— 不会被复制或存储。

在一个 500 行的 JSON 工具结果上实测：**27665 → 18812 tokens，节省 32.0%**，变换策略 `router:smart_crusher:0.54`，FATAL 行依然保留且被模型正确复述。逐请求的 token 计量出现在响应头（`x-headroom-tokens-before/after/saved`、`x-headroom-transforms`），累计值写入 `.headroom/savings_events.jsonl`。

### 代理需要的三个设置

| 设置 | 值 | 原因 |
| --- | --- | --- |
| `--mode` | `token` | `cache` 模式会冻结历史轮次以保护 provider 前缀缓存；被冻结的内容永不压缩，在一个 500 行工具结果上实测节省为 **零**。`token` 模式不冻结。 |
| `HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS` | `0` | 此环境下 HF tokenizer 下载无法完成，导致每个请求都卡满超时（约 10 秒）。禁用后 `opt_ms` 降到 26–66ms。 |
| 打过补丁的 venv | 由 `setup-proxy-venv.cmd` 处理 | `uvx` 会重建临时环境，源码补丁会丢失。参见[顶层 README 中的响应头补丁](../README.zh.md#为此必须修掉的一个上游-bug)。 |

### 代理不会自动启动

没有任何东西会替你拉起它，而指向已停止代理的 provider 会直接失败，不会回退。请把它作为受管后台任务启动，并在需要压缩期间保持运行。

未被覆盖的 provider 不受代理停止影响，所以这不会危及你的日常会话。

## 启动器是可选的

bundle 直接用 `PATH` 上的 `uvx` 拉起 `headroom mcp serve`，不需要任何包装脚本：

```
uvx --from "headroom-ai[mcp]" headroom mcp serve
```

因为 MCP stdio 服务由传输层（cross-spawn）直接 spawn、不经过沙箱子进程服务，它继承 Host 权限 —— uv 与 Headroom 直接写各自标准的用户级位置（`~/.cache/uv`、`~/.headroom` 等），**不**需要把缓存钉进工作区。补丁的 `env` 只设三个开关：`HEADROOM_BEACON=off`、`HEADROOM_UPDATE_CHECK=off`、`HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS=120`。

`bin/headroom-mcp.cmd`（Windows）与 `bin/headroom-mcp.sh`（POSIX）是**可选的独立便捷包装**，仅供**手动测试** —— bundle 不调用它们。手动运行它们时，它们会把 uv/Headroom 的缓存与状态目录固定到工作区内，并从 `HEADROOM_DSH_WORKSPACE`（或脚本自身往上两级）解析工作区根目录，让一次手动运行自成一体。

### 启动器与代理可覆盖的变量

这些变量由启动器与代理读取，而非 bundle 那条 `uvx` 调用：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `HEADROOM_DSH_WORKSPACE` | 脚本往上两级 | 手动运行启动器时的工作区根目录 |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | 限制词表加载卡顿 |
| `HEADROOM_MODE` | `token` | 代理压缩模式（`token` 或 `cache`） |
| `HEADROOM_PORT` | `8787` | 代理监听端口 |
| `HEADROOM_UPSTREAM_URL` | *（无 —— **必需**）* | 代理上游；参数 1 优先级更高 |
| `HEADROOM_PROXY_VENV` | `<workspace>/.proxy-venv` | 打过补丁的代理环境位置 |
| `HEADROOM_PYTHON` | `3.12` | `setup-proxy-venv.cmd` 请求的解释器版本 |
| `HEADROOM_PROXY_EXTRAS` | `proxy` | 安装进该 venv 的 Headroom extras |

## 安装

本目录的上一级就是仓库根目录；请先克隆，再从那里操作。让 Harness agent 把 `plugin/` 作为本地 bundle 安装 —— 它会以 `action: install_bundle` 和本目录作为 target 调用 `plugin_manager` 工具：

```
plugin_manager  action=install_bundle  target=<仓库路径>\plugin
```

这是受支持的路径，也是实际采用的方式。它会在 profile 中运行 pnpm，把 `@local/dsh-headroom` 链接进 `~/.dsh/profiles/<profile>/node_modules`，并把补丁应用到当前 profile（live profile 无需重启）。成功时返回 `application: applied` 且 `warnings` 为空。

不要手工编辑 profile 的 `package.json` 或 `cordis.patch.yml`；bundle 拥有自己的补丁文件，而 profile 由包管理器掌管。

### 无需配置路径

MCP 行的 `command` 不含目录分量，stdio 传输层通过 `PATH`（`cross-spawn`）解析它 —— 所以安装位置和 Host 的工作目录都不再重要，也没有 `cwd`、`DSH_HEADROOM_ROOT` 或相对启动器路径需要你操心。

## 验证

四项独立检查，从最省事的开始。

### 1. 补丁能被解析且结构正确

```powershell
node -e "const{createRequire}=require('module');const r=createRequire(process.env.DSH_CHECKOUT+'/node_modules/');const y=r('yaml');const d=y.parse(require('fs').readFileSync('plugin/cordis.patch.yml','utf8'));console.log(JSON.stringify(d,null,2))"
```

预期得到一个顶层数组，其中包含一个 `insert` 行，其 `config.serverName` 为 `headroom`，且 `config.command` 为 `uvx`。

### 2. MCP server 能完成握手

把三行 JSON-RPC 写入文件，再管道输入。必须使用 PowerShell 管道 —— 用管道传给 Node 的 `child_process.spawn` 会撞上沙箱的 EPERM 边界。下面用可选的 `headroom-mcp.cmd` 包装来跑握手（bundle 本身直接跑等价的 `uvx --from "headroom-ai[mcp]" headroom mcp serve`，换成那条命令也一样）：

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

`initialize` 应报告 `serverInfo.name = "headroom"`。短生命周期的管道可能只返回 `initialize` 响应，因为 stdin 在异步的 `tools/list` 完成之前就关闭了 —— 这是 shell 的产物，不是启动器的 bug。要稳定看到工具列表，请保持 stdin 打开直到 `id:2` 响应到达：

```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/d /s /c "<仓库路径>\plugin\bin\headroom-mcp.cmd"'
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

预期得到一个 `tools` 数组，包含 `headroom_compress`、`headroom_retrieve`、`headroom_stats`。

### 3. 在 Harness 中确认

安装后，`plugin_manager` 的 `list_plugins` 应显示 `headroom-mcp` 行处于 `active` 状态，且 agent 应能看到三个 `mcp__headroom__*` 工具。

### 4. 端到端验证器

[`verify/verify_headroom.py`](verify/verify_headroom.py) 针对运行中的代理检查整条链路：

```powershell
plugin\bin\headroom-proxy.cmd          # 在另一个窗口，或作为后台任务
.proxy-venv\Scripts\python.exe plugin\verify\verify_headroom.py `
    --credentials "$env:USERPROFILE\.dsh\.credentials.yaml"
```

它运行四项检查并打印 `OVERALL: PASS`，任一失败都会以非零码退出：

| 检查 | 证明什么 |
| --- | --- |
| `header` | h11 接受所有脱敏后的 `x-headroom-model` 值（并展示原始值失败） |
| `discovery` | `GET /v1/models` 正常透传，因此 provider 选择器可用 |
| `stream` | 一次真实的 SSE 补全在尾随空格模型 id 下成功往返 |
| `compress` | 500 行工具结果被压缩，且 FATAL 行存活 |

`--only header` 可运行那个不需要密钥、不需要网络的离线检查。密钥来自 `HEADROOM_TEST_API_KEY`，或通过 `--credentials` / `--credential-ref` 从凭据文件读取。

## 卸载

```
plugin_manager  action=remove_bundle  target=@local/dsh-headroom
```

之后若想回收磁盘空间，可删除工作区缓存目录：
`.uv-cache`、`.uv-tools`、`.uv-bin`、`.tiktoken-cache`、`.headroom`、`.proxy-venv`。

## 一个已知但无害的警告

`headroom_compress` 与 `headroom_stats` 的结果中会包含：

```
"proxy": {"url": "http://127.0.0.1:8787", "status": "unreachable", ...},
"warning": "Configured proxy http://127.0.0.1:8787 is unreachable ..."
```

这是**预期之中且无害的**。Headroom 每次调用都会探测那个可选的本地 HTTP 代理，代理未运行时即报告不可达。独立模式 —— 在进程内压缩、原文存于本地 CCR 存储 —— 完全不需要代理，且 `headroom_retrieve` 由 `"source": "local"` 提供。若想消除该探测，可通过启动器的 `env` 把 `HEADROOM_PROXY_URL` 指向一个运行中的代理。

## 限制

- **两种模式，作用范围不同。** MCP 那一半暴露的是需要 agent 主动调用的按需工具；代理那一半是透明压缩，但只对你重定向过去的 provider 生效。`bin/headroom-proxy.cmd` 是代理启动器 —— 没有任何东西会替你启动它，它也不属于 MCP 那一行。
- **覆盖范围取决于 provider。** provider 通过设置 `baseURL: http://127.0.0.1:8787/v1` 来接入。一个自带 adapter 的插件（例如把 `opencode.ai/zen` 写死的 `opencode2dsh`）无法被重定向，因此不会被压缩。
- **最新的用户消息永远不被压缩。** Headroom 有意保护它，所以当请求主体位于最后一轮用户消息时压缩量为零。
- **被保护的工具永不压缩。** `Read`、`Glob`、`Grep`、`Write`、`Edit`、`WebFetch`、`WebSearch`、`headroom_retrieve`（以及小写变体）按名称被排除，因此文件读取与搜索输出会原样通过 —— 这是出于正确性的选择，因为对原始文件内容或已检索原文做有损压缩会破坏工作成果。验证脚本的 `compress` 检查正是因此使用自定义工具名（`query_logs`）；若用合成的 `read` 结果，会报告 0% 而看起来像失败。真正会被压缩的是未被保护工具的大体积输出（数据库行、API 响应）。
- **压缩取决于重复性的结构。** 一个 400 行的 JSON 数组节省了 41.2%（`router:smart_crusher:0.47`），而同样这些行以 JSON Lines 形式保存时只节省 5.8% —— SmartCrusher 利用的是数组结构。`headroom_compress` 会返回它实际应用的 `transforms`，所以意外的低节省是可见的而非静默的。
- **代理必须处于运行状态。** 指向已停止代理的 provider 会直接失败，而不会回退到直连上游。
- **首次运行较慢。** `uvx` 需要在首次启动时安装 `headroom-ai[mcp]` 及其依赖。请预期延迟和网络访问；之后走缓存。
- **散文压缩需要 ML 模型，且预热较慢。** 纯文本压缩走 Headroom 的 Kompress 后端：首次使用时下载一个 ONNX 模型（约 260 MB），之后冷启动预热约需两到三分钟。预热完成前散文会原样通过，而结构化内容（JSON、日志、代码）正常压缩 —— 可在代理的 `/debug/warmup` 看 `kompress: loaded`。两条路径在这里有差别：代理环境带 ONNX 后端，而 MCP 行只装 `headroom-ai[mcp]`，因此 `headroom_compress` 压缩结构化内容、散文则原样返回。
- **`uvx` 必须在 `PATH` 中。** MCP 行按名字调用 `uvx`。
- **MCP 行跨平台。** `uvx` 在 Windows（`uvx.exe`）、macOS、Linux 上都是同一个名字，因此 MCP 行没有 `.cmd`/`.sh` 的平台区分。可选的 `.cmd`/`.sh` 包装仅供手动测试。
- **安装后即可用。** MCP 行经 `PATH` 上的 `uvx` 启动，无论 bundle 装在哪、Host 的工作目录是什么都能工作 —— 安装后 `headroom-mcp` 行应为 `active`，三个工具即可调用。
- **无遥测，且更新检查已关闭**（`HEADROOM_BEACON=off` 加上 `HEADROOM_UPDATE_CHECK=off`，两条独立开关的通路），但压缩库本身是本地运行的第三方代码，会接触到你的内容。
