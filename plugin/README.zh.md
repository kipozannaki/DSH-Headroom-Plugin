# @local/dsh-headroom

一个纯配置的 Cordis bundle，把 **Headroom 的 MCP server** 注册进 DeepSeek Harness。

它向 Harness 插件列表追加一行 —— 一个通过 stdio 拉起 Headroom 的 `@deepseek-ai/dsh-mcp-client` 条目 —— 于是 agent 无需离开对话，就能按需压缩大块内容并取回原文。

**[English](README.md)** · [顶层文档](../README.zh.md)

- 包名：`@local/dsh-headroom` v1.0.0
- Bundle 补丁：[`cordis.patch.yml`](cordis.patch.yml)
- MCP 启动器：[`bin/headroom-mcp.cmd`](bin/headroom-mcp.cmd)（Windows）/ [`bin/headroom-mcp.sh`](bin/headroom-mcp.sh)（POSIX）
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

## 为什么需要启动器

MCP 启动器通过 `uvx` 按需安装 Headroom。在沙箱化的 Harness（workspace-write）下，uv 与 Headroom 的默认状态目录位于工作区之外且不可写，因此启动器会在 exec `uvx` 之前把它们全部固定到工作区内：

| 变量 | 值 | 原因 |
| --- | --- | --- |
| `UV_CACHE_DIR` | `<workspace>/.uv-cache` | uv 的包缓存 |
| `UV_TOOL_DIR` | `<workspace>/.uv-tools` | uv 工具环境 |
| `UV_TOOL_BIN_DIR` | `<workspace>/.uv-bin` | uv 工具 shim |
| `TIKTOKEN_CACHE_DIR` | `<workspace>/.tiktoken-cache` | 防止 tiktoken 词表下载卡死 |
| `HEADROOM_WORKSPACE_DIR` | `<workspace>/.headroom` | 沙箱下 Headroom 无法写 `~/.headroom` |
| `HEADROOM_BEACON` | `off` | 关闭匿名使用信标（本地优先，无遥测） |
| `HEADROOM_UPDATE_CHECK` | `off` | 关闭每日一次的 PyPI 版本探测 —— 由独立于信标的开关控制 |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | 限制词表加载卡顿 |

工作区根目录在每个启动器开头只解析一次：

1. 若设置了 `HEADROOM_DSH_WORKSPACE` 环境变量则用之；否则
2. 从脚本自身所在目录往上两级（`plugin/bin` → 工作区根目录）。

因此 bundle 可以迁移位置，只要补丁的 `cwd` 表达式能解析成功，它在任何工作目录下都能工作（见[迁移 bundle 位置](#迁移-bundle-位置)）。

最终执行的命令是：

```
uvx --from "headroom-ai[mcp]" headroom mcp serve
```

### 可覆盖的变量

上表中的每个值都是默认值，可在启动前通过设置变量替换。以下变量会被读取，但未列入上表，因为你很少需要它们：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `HEADROOM_DSH_WORKSPACE` | 脚本往上两级 | 其余所有路径都派生自这个工作区根目录 |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | 限制 MCP server 的词表加载卡顿 |
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

**安装前请先修改 [`cordis.patch.yml`](cordis.patch.yml) 中的 `command`** —— 参见[迁移 bundle 位置](#迁移-bundle-位置)。

不要手工编辑 profile 的 `package.json` 或 `cordis.patch.yml`；bundle 拥有自己的补丁文件，而 profile 由包管理器掌管。

### 迁移 bundle 位置

MCP 的 `command` 会被 SDK 以 `shell: false` **原样** spawn（`@modelcontextprotocol/client/dist/stdio.mjs`），而 `dsh-mcp-client` 的 config schema 把它声明为普通的 `z.string().required()`，不做任何路径解析 —— 该模块根本没有引入 `path`。Loader 的相对路径锚定只覆盖行的 `name`（其 `anchorInsertedPluginNames` 只改写 `entry.name`），**不覆盖**插件自身的 config 值。因此相对 `command` **不会**相对于补丁文件解析。

但它是相对于 `cwd` 解析的 —— 而 `dsh-mcp-client` 恰好接受 `cwd` 配置项（`lib/index.js:786`，默认 `""`），并把它转发给 SDK 的 stdio 传输层（`:44`）。这正是纯配置补丁也能做到可迁移的原因：

```yaml
cwd: !!js process.env.DSH_HEADROOM_ROOT || process.cwd()
command: plugin\bin\headroom-mcp.cmd
```

从仓库根目录启动 Harness 时，回退值已经正确；从别处启动时，由 `DSH_HEADROOM_ROOT` 提供根目录。启动器本身同样不含硬编码 —— 每个都从 `HEADROOM_DSH_WORKSPACE` 解析自己的工作区根目录，否则回退到自身所在位置往上两级。

`!!js` 是 Cordis 的 entry-list 方言，在 Host 中于行激活时以 `with (ctx) { return eval(expr) }` 求值。该作用域暴露 `process` 等 Node 全局对象，但**不暴露** `__dirname`、`__filename`、`require`、`module` —— 所以无法自动推导出仓库相对路径，它只能来自环境变量或工作目录。

另请注意，DSH 在把环境交给 MCP 子进程之前，会清洗任何匹配 `/KEY|PASSWORD|SECRET|TOKEN/i` 的名字，以及所有 `DSH_*` 名字（`dsh-subprocess/lib/index.js:32,52`）。本 bundle 的 `HEADROOM_*` 命名原样通过；而 `DSH_HEADROOM_ROOT` 是由 Loader 在那次清洗**之前**读取的 —— 它在 Host 中求值，而非在子进程中。因此启动器自己读取的变量，请优先使用 `HEADROOM_DSH_WORKSPACE`。

## 验证

四项独立检查，从最省事的开始。

### 1. 补丁能被解析且结构正确

```powershell
node -e "const{createRequire}=require('module');const r=createRequire(process.env.DSH_CHECKOUT+'/node_modules/');const y=r('yaml');const d=y.parse(require('fs').readFileSync('plugin/cordis.patch.yml','utf8'));console.log(JSON.stringify(d,null,2))"
```

预期得到一个顶层数组，其中包含一个 `insert` 行，其 `config.serverName` 为 `headroom`，且 `config.command` 指向启动器。

### 2. MCP server 能完成握手

把三行 JSON-RPC 写入文件，再管道输入。必须使用 PowerShell 管道 —— 用管道传给 Node 的 `child_process.spawn` 会撞上沙箱的 EPERM 边界。

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

安装后，`plugin_manager` 的 `list_plugins` 应显示 `headroom-mcp` 行处于启用状态，且 agent 应能看到三个 `mcp__headroom__*` 工具。

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
- **`uvx` 必须在 `PATH` 中。** 启动器按名字调用 `uvx`。
- **Windows 启动器是 `.cmd`。** 它无法在没有 shell 的情况下被直接 spawn；`dsh-mcp-client` 以 `command` 形式调用它时，在 Windows 上会经由 `cmd.exe`。`.sh` 启动器是 POSIX 等价物。
- **补丁通过 `cwd` 定位启动器。** 只要你从仓库根目录启动 Harness，它开箱即用；否则请把 `DSH_HEADROOM_ROOT` 设为该根目录，让 `!!js` 表达式能找到它。
- **无遥测，且更新检查已关闭**（`HEADROOM_BEACON=off` 加上 `HEADROOM_UPDATE_CHECK=off`，两条独立开关的通路），但压缩库本身是本地运行的第三方代码，会接触到你的内容。
