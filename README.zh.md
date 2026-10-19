# DeepSeek-Harness-Headroom-Plugin

![bundle](https://img.shields.io/badge/bundle-v1.0.0-CB3837?logo=npm&logoColor=white)
![license](https://img.shields.io/badge/license-Apache--2.0-brightgreen)
![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![DeepSeek Harness](https://img.shields.io/badge/DeepSeek_Harness-plugin-4D6BFE?logo=deepseek&logoColor=white)

把 [Headroom](https://github.com/headroomlabs-ai/headroom) —— 一个本地优先的上下文压缩工具包 —— 接入 **DeepSeek Harness**，作为一个原生插件。

安装之后，你的 DSH 可以按需压缩大块内容并逐字节取回原文；同时，任何指向内置代理的 provider 都会获得**透明压缩** —— 你不需要改动任何提示词。

**[English](README.md)**

---

## 你能得到什么

通过 Headroom 自带的 MCP server 暴露三个原生工具：

| 工具 | 作用 |
| --- | --- |
| `mcp__headroom__headroom_compress` | 压缩大块内容（工具输出、文件、日志、搜索结果）→ 返回压缩后文本 + 一个取回哈希 |
| `mcp__headroom__headroom_retrieve` | 用该哈希取回**逐字节一致**的原文 |
| `mcp__headroom__headroom_stats` | 会话统计：压缩次数、节省 token、预估成本 |

两种使用方式，彼此独立：

**一、按需工具 —— 对任何 provider 都有效。** 由模型自行决定何时调用。你的流量本身不发生任何变化，只有 agent 主动使用它时才获得压缩。

**二、透明压缩 —— HTTP 代理。** 经过被重定向 provider 的每一个字节都会被自动压缩，无论模型是否主动要求。在一个 500 行的工具结果上实测：

```
压缩前  : 27665 tokens
压缩后  : 18812 tokens
节省    :  8853 tokens  (32.0%)
变换策略 : router:smart_crusher:0.54
```

那条 FATAL 行（id 67）在压缩后依然保留，模型也确实基于它给出了正确答案。压缩是**可逆的**：原文存放在本地存储中，取回时逐字节一致 —— 所以它只是把内容延后，而不是丢弃。逐字节一致性是**存储**的性质，而非压缩后文本的性质：模型内联读到的是有损版本，原文需要通过取回来恢复。

## 安装

**前置条件：** 一个可用的 DSH profile，以及 `PATH` 中的 `uv`/`uvx`。

如果 `uvx --version` 还打不出版本号，先装 `uv` —— 这是唯一的前置条件，且 Windows、macOS、Linux 用同一条思路：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 或者，如果你已有 Python 和 pip
pip install uv
```

装完重开终端，确认 `uvx --version` 有输出。除此之外不需要任何东西：`uvx` 会自己拉取 Headroom 及其全部 Python 依赖，**不需要**你创建 Python 环境，也**不需要**编译任何包。

把这个仓库克隆到任意位置 —— MCP 行通过 `PATH` 上的 `uvx` 启动，不关心 bundle 装在哪里；只有 `install_bundle` 那一步需要一个绝对路径来定位 bundle。

```bash
git clone <this-repo> dsh-headroom
cd dsh-headroom
```

不需要任何构建。Headroom 本身会在首次使用时由 `uvx` 拉取，代理环境由其启动器按需创建。

### 第 1 步 —— 无需任何配置

随附的补丁是零配置的 —— 它通过 `PATH` 上的 `uvx` 直接拉起上游 `headroom mcp serve`，因此不需要编辑任何东西：

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

`command` 不含目录分量，stdio 传输层通过 `PATH` 解析它（`cross-spawn`），所以安装位置和 Host 的工作目录都不再重要 —— 这正是纯配置补丁也能做到可迁移的原因。`uvx` 在 Windows（`uvx.exe`）、macOS、Linux 上都是同一个名字，因此 MCP 行没有任何 `.cmd`/`.sh` 的平台区分。`args` 作为子进程 argv 原样传入，`headroom-ai[mcp]` 无需引号。

### 第 2 步 —— 安装 bundle

```
plugin_manager  action=install_bundle  target=<本仓库绝对路径>\plugin
```

它会在你的 profile 中运行 `pnpm`，把 `@local/dsh-headroom` 链接进 `~/.dsh/profiles/<profile>/node_modules`，并把补丁应用到当前 profile。成功时返回 `application: applied` 且 `warnings` 为空。如果你的 profile 不是 live profile，请重启 DSH。装好后 `headroom-mcp` 行即为 `active`，三个 `mcp__headroom__*` 工具马上可用 —— 不需要从任何特定目录启动 Harness。

> 只有这一个路径无法避免绝对写法 —— `install_bundle` 需要由你告知 bundle **在哪里**。它之后的一切都是相对的。

### 第 3 步 —— 卸载

```
plugin_manager  action=remove_bundle  target=@local/dsh-headroom
```

### 关于环境变量

DSH 会清洗交给 MCP 子进程的环境：任何匹配 `/KEY|PASSWORD|SECRET|TOKEN/i` 的名字都会被丢弃，任何以 `DSH_` 开头的名字同样如此（`dsh-subprocess/lib/index.js:32,52`）。本 bundle 的变量全部以 `HEADROOM_*` 命名，因此可以原样通过 —— 但如果你要自行添加形似凭据的变量名，这一点值得先知道。

`HEADROOM_DSH_WORKSPACE` 可覆盖启动器的工作区探测。只有当你在迁移过或符号链接的位置调用启动器时才需要它。

## 验证安装

[`plugin/verify/verify_headroom.py`](plugin/verify/verify_headroom.py) 端到端地证明整条链路 —— 脱敏器、模型发现、真实 SSE 流、以及一次真实压缩：

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

每个检查都会打印自己的 `RESULT: PASS` 行以及它观测到的数字，因此失败的运行会明确指出是哪一阶段失败以及原因。`--only header` 可单独运行那个不需要密钥、不需要网络的离线检查。失败时以非零码退出，可以直接接入 CI。

[`plugin/README.md`](plugin/README.md) 另外记录了 MCP 握手检查及其余手工验证步骤。

## 透明压缩（代理）

启动代理 —— **没有任何东西会自动拉起它**，而且它需要被告知转发到哪里：

```powershell
plugin\bin\headroom-proxy.cmd https://your-provider.example/v1
```

这里**有意不设内置上游**。一个会静默转发到你并未选择的端点的代理，会把你的内容和 API key 发往意料之外的地方，因此启动器会直接报错退出而不是猜测。请通过参数、`HEADROOM_UPSTREAM_URL`，或已存在的 `OPENAI_TARGET_API_URL` 提供它。

然后把某个 provider 的 `baseURL` 指过来：

```yaml
# 你的 profile cordis.patch.yml，位于某个 llm-pi-ai provider 内
baseURL: http://127.0.0.1:8787/v1
```

代理会转发到 `OPENAI_TARGET_API_URL`，并原样透传客户端的 `Authorization` 头，因此 provider 密钥始终是 DSH 自己发送的那个 —— 不会被复制、拦截或存储。逐请求的 token 计量出现在响应头（`x-headroom-tokens-before/after/saved`、`x-headroom-transforms`），累计值写入 `.headroom/savings_events.jsonl`。

有三个设置很关键，且缺一不可：

| 设置 | 值 | 原因 |
| --- | --- | --- |
| `--mode` | `token` | `cache` 模式会冻结历史轮次以保护 provider 的前缀缓存；被冻结的内容永不压缩，实测节省为 **零**。`token` 模式不冻结。对于两者都不冻结的内容，两种模式行为一致。 |
| `HEADROOM_HF_TOKENIZER_LOAD_TIMEOUT_SECS` | `0` | 此环境下 HF tokenizer 下载永远无法完成，导致每个请求都卡满超时（约 10 秒）。禁用该下载后，`opt_ms` 从约 10000ms 降到 26–66ms。 |
| 打过补丁的 venv | 由 `bin/setup-proxy-venv.cmd` 处理 | `uvx` 每次都会重建临时环境，源码补丁会随之丢失。 |

## 为此必须修掉的一个上游 bug

Headroom 会把调用方的模型 id 写进响应头：

```python
headers["x-headroom-model"] = model
```

而 DSH 的模型选择器给出的 id 是 `deepseek-v4.1-flash ` —— **带一个尾随空格**。HTTP 头值不允许包含这个字符，于是 `h11`（uvicorn 的 HTTP/1.1 协议栈）在上游已经返回 200 *之后* 拒绝了该响应：

```
h11._util.LocalProtocolError: Illegal header value b'deepseek-v4.1-flash '
→ 客户端看到：httpx.RemoteProtocolError: Server disconnected without sending a response
```

症状是**每一个流式请求都失败，而客户端侧没有任何解释**。

[`plugin/patch_headroom_model_header.py`](plugin/patch_headroom_model_header.py) 在 `headroom/proxy/cost.py` 中新增了 `header_safe_model()`（与既有的 `header_safe_transforms` 对称），并把全部五处 `x-headroom-model` 赋值改走该函数。它会去掉首尾空白、替换控制字符，并在没有可用值时整个省略该头。

它**只改这一个计量头** —— 不碰路由，不碰请求体 —— 因此不可能改变模型看到的内容。尾随空格在上游本身是无害的（两种写法都返回 HTTP 200），所以脱敏不损失任何信息。

该脚本幂等，按文件报告 `patched` / `already`，并支持 `--check` 只验证不写入。`bin/setup-proxy-venv.cmd` 会在每次启动代理时自动应用它，因此升级或重建过的 venv 不会静默丢掉这个修复。

补丁打在**已安装的包**上，而不是某个源码检出上，所以全新克隆下来无需任何手工步骤即可自我修复。这里没有任何东西依赖 Headroom 源码树：

```
[setup] applying header-safety patch
  proxy/cost.py                 -> patched
  proxy/handlers/streaming.py   -> patched (1 site(s))
  proxy/handlers/openai.py      -> patched (1 site(s))
  proxy/handlers/anthropic.py   -> patched (1 site(s))
  proxy/handlers/gemini.py      -> patched (2 site(s))
  syntax OK for all 5 files
```

## 目录结构

| 路径 | 作用 |
| --- | --- |
| [`plugin/`](plugin/) | **可安装的 DSH bundle** —— manifest、Cordis 补丁、可选启动器 |
| [`plugin/cordis.patch.yml`](plugin/cordis.patch.yml) | 插入 `headroom-mcp` 行（一个 `@deepseek-ai/dsh-mcp-client` 的 stdio 条目，经 `uvx` 拉起上游 `headroom mcp serve`） |
| [`plugin/bin/headroom-mcp.cmd`](plugin/bin/headroom-mcp.cmd) | 可选的 MCP 便捷包装（Windows），仅供**手动测试** —— bundle 直接用 `uvx`，不调用它；[`headroom-mcp.sh`](plugin/bin/headroom-mcp.sh) 为 POSIX 等价物 |
| [`plugin/bin/headroom-proxy.cmd`](plugin/bin/headroom-proxy.cmd) | 代理启动器 —— token 模式，不自动启动 |
| [`plugin/bin/setup-proxy-venv.cmd`](plugin/bin/setup-proxy-venv.cmd) | 创建 `.proxy-venv` 并应用响应头补丁；幂等 |
| [`plugin/patch_headroom_model_header.py`](plugin/patch_headroom_model_header.py) | 响应头安全补丁；`--check` 只验证不写入 |
| [`plugin/verify/verify_headroom.py`](plugin/verify/verify_headroom.py) | 端到端验证器；失败时非零退出 |
| [`plugin/upstream/dsh.py`](plugin/upstream/dsh.py) | **新增的上游注册器**：让 `headroom mcp install` 能写 DSH profile 配置 |
| [`plugin/patch_headroom_mcp_registry.py`](plugin/patch_headroom_mcp_registry.py) | 把该注册器安装进任意 Headroom 源码树；幂等，支持 `--check` |

> 上游 Headroom 源码**不**在本仓库内。那是一棵 68 MB 的第三方代码树，运行时没有任何东西读取它，因此本仓库只保留我们自己的代码，加上两个修改上游的补丁脚本。把补丁脚本指向你手上的任意 Headroom 树即可 —— `.proxy-venv` 里那份已安装的包，或你自己的 checkout。

### 两条集成路径

两条都已交付，它们是互补而非重复的关系：

1. **Bundle（你实际安装的那个）。** `plugin/` 通过 DSH 的 `dsh-mcp-client` 行注册 Headroom 的 MCP server。纯配置 —— 不运行任何 Host 或 Client JavaScript。
2. **上游注册器（源码补丁）。** [`plugin/upstream/dsh.py`](plugin/upstream/dsh.py) 把 DSH 加进 Headroom 自己的 `mcp_registry`，于是 Headroom 能像它已有的 Claude Code、Codex、OpenCode 那样，把自己安装进 DSH。这是该集成在长期来看更合适的归宿；bundle 之所以存在，是因为纯配置安装不需要等上游发版。

`patch_headroom_mcp_registry.py` 负责应用这个注册器：放入 `dsh.py`，并在 `__init__.py` 和 `install.py` 中各加一行 import 与一行注册表条目。它是幂等的，且已验证能在已发布的 0.41.0 上复现出可用的注册器：

```
python plugin/patch_headroom_mcp_registry.py --target .proxy-venv/Lib/site-packages/headroom
```

期望看到的安装状态：

```
  mcp_registry/dsh.py                -> patched
  mcp_registry/__init__.py           -> patched
  mcp_registry/install.py            -> patched
  dsh.py parses; registered in __init__.py and install.py
registrar integration OK
```

## 诚实的限制

我们更希望你提前知道这些，而不是在生产环境里才发现。

- **只有被重定向的 provider 才会被压缩。** 代理是通过 `baseURL` 插入的，所以一个自带 adapter、把端点写死的插件无法被覆盖。`opencode2dsh` 正是这种情况：它的 config schema 里没有 `baseURL`/`zenBaseUrl` 字段，不读任何环境变量，且其 `zenBaseUrl` 构造参数从不由 config 填充 —— 因此它永远指向 `https://opencode.ai/zen`。
- **没有「自动跟随用户模型」这种模式。** 最显而易见的接缝 —— `ctx.llm` 的 `llm/stream` waterfall —— 无法改写路由：按契约，由 agent loop 构造的请求 "arrives deep-frozen (**mutation throws**)"，监听器只能读，不能改 `provider`/`model`。provider 级 `baseURL` 重定向是唯一受支持的插入点。`agent-default-model` 本身也只接受三个静态字段，没有 `auto` 或 `follow` 取值。provider 选择始终是按会话进行的，这就是官方设计的机制。
- **最新的用户消息永远不被压缩。** Headroom 有意保护 `last_user_item_idx`，所以当请求的主体位于最后一轮用户消息时，压缩量为零（`router:protected:user_message`）。主体位于工具结果或更早轮次时才会产生节省。
- **最占体积的工具结果会被有意跳过压缩。** Headroom 按名称保护 `Read`、`Glob`、`Grep`、`Write`、`Edit`、`WebFetch`、`WebSearch`、`headroom_retrieve`（以及小写变体），因此文件读取与搜索输出 —— 通常是编码会话中体积最大的部分 —— 会原样通过。这是出于正确性的选择，而非疏忽：对模型正在逐字节修补的原始文件内容，或对已检索出的原文做有损压缩，会破坏工作成果。真正会被压缩的是未被保护工具的大体积输出：数据库行、API 响应、以及自定义工具结果中的大块 JSON —— 在一个 500 行负载上以自定义工具名实测节省 33.7%（9227 tokens）。
- **压缩取决于结构，而非体积。** 一个 400 行的 JSON 数组节省了 41.2%（`router:smart_crusher:0.47`），而同样这些行以 JSON Lines 形式保存时只节省 5.8% —— SmartCrusher 利用的正是数组结构。`headroom_compress` 会返回它实际应用的 `transforms`，所以意外的低节省是可见的而非静默的。
- **代理必须处于运行状态**，否则被重定向的 provider 会直接失败而不是回退。未被覆盖的 provider 不受影响，所以代理停掉不会破坏你的日常会话。
- **MCP 首次启动较慢。** `uvx` 需要安装 `headroom-ai[mcp]` 及其依赖，并且需要网络。之后的启动走缓存。
- **这不是重新实现。** 压缩运行在 Headroom 自己的进程里，使用它已发布的代码。本集成的改动只有响应头补丁和新增的注册器，两者都在 `plugin/` 下。
- **无遥测，且更新检查已关闭。** 启动器同时禁用了两条对外通路：`HEADROOM_BEACON=off` 关闭那个匿名、不含内容的会话摘要（它在上游是**默认开启**的），`HEADROOM_UPDATE_CHECK=off` 关闭每日一次的 PyPI 版本探测 —— 后者由独立开关控制，否则仍会发出请求。仅本地的 `HEADROOM_TELEMETRY` 开关默认关闭，永不离开本机。尽管如此，Headroom 仍是本地运行的第三方代码，会接触到你的内容 —— 在处理敏感数据前请先阅读它。

## 环境说明

MCP 行由传输层（cross-spawn）直接 spawn，不经过沙箱子进程服务，因此继承 Host 权限 —— uv 与 Headroom 直接写各自标准的用户级位置（`~/.cache/uv`、`~/.headroom` 等），**不**需要把缓存钉进工作区。补丁的 `env` 只设三个 `HEADROOM_*` 开关：

| 变量 | 值 | 作用 |
| --- | --- | --- |
| `HEADROOM_BEACON` | `off` | 匿名使用信标 |
| `HEADROOM_UPDATE_CHECK` | `off` | 每日一次的 PyPI 版本探测（另一条独立对外通路） |
| `HEADROOM_TIKTOKEN_LOAD_TIMEOUT_SECONDS` | `120` | 限制词表加载卡顿 |

可选启动器（`headroom-mcp.cmd`/`.sh`）与代理启动器（`headroom-proxy.cmd`、`setup-proxy-venv.cmd`）在你手动运行它们时，会把下面这些目录固定到工作区内 —— 每一条都对应开发过程中实际踩到过的失败：

| 变量 | 值 | 避免的问题 |
| --- | --- | --- |
| `UV_CACHE_DIR` / `UV_TOOL_DIR` / `UV_TOOL_BIN_DIR` | `<workspace>/.uv-*` | uv 缓存与 shim 的权限错误 |
| `TIKTOKEN_CACHE_DIR` | `<workspace>/.tiktoken-cache` | tokenizer 词表下载卡死 |
| `HEADROOM_WORKSPACE_DIR` | `<workspace>/.headroom` | 写 `~/.headroom`（CCR 存储）报 `[WinError 5]` |
| `HEADROOM_DSH_WORKSPACE` | *（可选）* | 覆盖工作区根目录探测 |

`.uv-cache`、`.uv-tools`、`.uv-bin`、`.tiktoken-cache`、`.headroom`、`.proxy-venv` 存放下载的包和运行时状态。可以安全删除以回收磁盘空间；下次启动会重新安装。

## 许可证

本项目为 **Apache-2.0** —— 见 [LICENSE](LICENSE)。它是围绕 Headroom 的集成，而 Headroom 本身也是 Apache-2.0；Headroom 所依赖组件的第三方署名收录在 [NOTICE](NOTICE)。
