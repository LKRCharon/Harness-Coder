# HarnessCoder

[English](README.md) | [简体中文](README.zh.md)

HarnessCoder 是一个面向真实仓库任务的本地 coding agent runtime 与评测框架。
它的 1.0 主线刻意收窄，只讲四件事：

- 基于事件日志的 agent loop
- 经过策略门控的工具执行
- trace / replay / eval
- 上下文治理：memory、compression、RepoMap

它不是 CoreCoder 的 fork，不是一个更小的 LangGraph，也不是 Web UI 项目。
第一个目标是做出一个可控的 runtime：模型每次决策、策略检查、工具结果、
状态更新和验证结果，都能写进可回放的 JSONL trace。

核心循环是动态的：

```text
state -> model decides action -> policy checks -> tool executes
      -> observation appended -> state updated -> model decides again
```

这点很重要，因为仓库任务通常不是固定 DAG。下一步该搜索、读文件、编辑还是
测试，取决于当前仓库、工具观察、失败输出、测试结果以及模型不断变化的计划。
DAG 或工作流框架可以用来组织 agent 外围的 eval pipeline，但 agent 本体仍然
应该是一个经过策略门控的动态循环。

## 当前状态

版本 `1.3.3` 已经是一个可运行的本地 runtime，支持真实 bugfix 与最小
greenfield eval loop、HC-Bench-20/40、trace replay、eval report、model profile
矩阵对比、上下文治理 prompt assembly、任务内 memory、compression metrics、
轻量 RepoMap、checkpoint/resume，以及用于审计和回放的大工具输出 artifact
存储。它还补上了跨 run 的 durable session，让 CLI/TUI 能处理“继续刚才那个
任务”这类跟进消息，同时每次 agent run 仍然有独立 trace。1.3.1/1.3.2 又补上
Context Budget v2 和 context ablation matrix，让上下文压缩、RepoMap、memory
这些能力可以从 trace 里解释，也可以在报告里做消融对比。1.3.3 补上真实模型
eval hygiene：更宽容的 action 解析、可复现的 Python 子进程命令，以及可在
trace/report 中审计的 model retry 指标。训练 trace 收集和 live eval 仍然分开：
HC-Train-40 用于训练池，HC-Bench-20/40 用于 heldout/control 评测。

当前包含：

- `ScriptedModel`：不用真实 LLM，模拟模型动作，便于验证 harness 本身。
- 本地工具：
  - `read_file(path, offset=0, limit=200)`
  - `search_code(query, path=".")`
  - `repo_map(query=None, max_tokens=1200, refresh=false)`
  - `write_file(path, content, overwrite=false)`
  - `edit_file(path, old, new)`
  - `run_tests(cmd=None, timeout=60)`
  - `run_command(cmd, timeout=30)`
- 每次工具调用前的小型 policy gate。
- `.harnesscoder/runs/<run_id>/trace.jsonl` 下的 JSONL trace。
- 大工具输出会在 trace/model context 中保留预览，并完整存到 run 的
  `artifacts/` 目录，带大小和 hash 元数据。
- `context_packed`、`checkpoint_created`、`run_resumed`、`test_result` 等事件，
  用于可靠性回放。
- `context_packed` 上的 Context Budget v2 字段，记录每个 section 的字符数、
  预算、preserved/reduced 标记、丢弃 block 数和总预算使用量。
- `.harnesscoder/sessions/<session_id>.json` 下的 durable session，以及
  `session_context_loaded` trace 事件，用于跨 run 跟进任务。
- `repo_map_built`、`repo_map_used` 事件，用于仓库级上下文治理。
- 通过 `python -m harnesscoder.replay` 生成 trace replay summary。
- 一个最小 eval harness：复制 fixture、运行 agent、执行测试、评分并生成
  Markdown report。
- fixture-backed bugfix eval：先复制 repo 到
  `.harnesscoder/eval-workspaces/...`，再让 agent 修改副本。
- greenfield eval：从几乎空的 fixture 开始，由 agent 创建源码和测试。
- case 级别的 `allowed_tools`、`step_budget`、`verifier` 字段，避免评测约束只藏在文字里。
- model profiles 和 Markdown eval matrix，用同一组 case 对比不同 provider。
- HC-Bench-20：原始 20 题 fixture-backed 成绩单，覆盖 bugfix、recovery、
  greenfield、context-governance 和 policy/safety。
- HC-Bench-40：更难的 heldout 成绩单，保留 HC-Bench-20 的可比性，并新增
  ProgramBench-style 编程修复、parser recovery、更丰富的 greenfield、大上下文
  定位和 policy/security case。
- HC-Train-40：40 个 fixture-backed 训练 case，用于 teacher/current-policy trace
  收集，并显式标注 `split=train` 和 `source=synthetic-microbenchmark`。
- `hc-bench-oracle` deterministic provider：先证明 benchmark 和 report pipeline
  可解，再比较真实模型。

常用 CLI：

```bash
python -m harnesscoder "看一下这个 repo 是做什么的"
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
python -m harnesscoder --session interview "继续刚才那个 repo 解释"
python -m harnesscoder --eval eval/cases.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_40.json
python -m harnesscoder --provider hc-bench-oracle --eval eval/hc_bench_20.json --context-ablations
```

当前 scripted model 会做一个小型 repo orientation：搜索项目相关信息、读取
`README.md`、列出文件，然后给出最终回答。

## TUI

HarnessCoder 也提供一个只依赖标准库的轻量终端 UI：

```bash
python -m harnesscoder --tui
```

在 TUI 里输入普通消息会启动一次 agent run 并写入新的 trace。运行期间 UI 会
继续刷新，在状态区展示最新 trace 事件，并在窄屏或短终端下折叠 header。也可
使用 slash commands 调用工具或切换运行配置：

```text
/help
/status
/model your-model-name
/model scripted
/provider openai-codex
/base-url https://your-openai-compatible-endpoint.example
/read README.md
/search HarnessCoder
/repo-map HarnessCoder
/edit README.md old new
/test python -m unittest discover -s tests
/run git status --short
/trace latest
/session interview
/reset-session
```

当前 TUI 定位很小：它只是 runtime 和 eval harness 的本地控制台，不是完整的
Claude Code clone。它现在支持 durable session：`/session <id>` 切换会话，
每个完成的 run 会把有限 turn 摘要写入 `.harnesscoder/sessions/`，下一次 run
会把 session context 通过同一套 prompt/trace 链路注入模型。

这个控制台现在通过一个小型 runtime control plane 做运行控制，而不是把逻辑
散落在 TUI 分支里。active run 期间会阻止会改变状态的命令，只保留 `/help`、
`/status`、`/trace` 这类只读控制。HC 借鉴 Hermes 的入口/runtime 分层，而不
复制它的多平台 Gateway 形态。

## 上下文治理

HarnessCoder 的上下文治理有三个任务内层次：

- Packed context：汇总 hot observations、cold trace history、已修改文件和预算。
- Working memory：保存任务内事实，例如 failing tests、explored files、
  relevant symbols、patch summary、verified facts、open questions。
- RepoMap：从 Python AST 中提取 imports、class、function、signature；对非 Python
  文本文件使用轻量 regex fallback，构建有 token 上限的仓库索引。

可以用 prompt modes 做 ablation：

```bash
python -m harnesscoder --context-mode none "inspect this repo"
python -m harnesscoder --context-mode pack "inspect this repo"
python -m harnesscoder --context-mode memory "inspect this repo"
```

`pack` 和 `memory` 模式默认启用 RepoMap injection，也可以单独关闭：

```bash
python -m harnesscoder \
  --context-mode pack \
  --repo-map-mode none \
  "inspect this repo"
```

每次模型调用前，`context_packed` trace 都会记录 Context Budget v2：每个 section
的 `raw_chars`、最终 `chars`、`budget`、`preserved`、`reduced` 和
`dropped_blocks`。当前任务契约会强保留；observations、packed context、session
context、RepoMap、working memory 这类低优先级 section 可以被裁剪或减少。Replay
和 eval report 会聚合 budget reductions、dropped blocks、总 context chars 和总
budget。

## OpenAI-Compatible Providers

MVP 包含两个可选的 OpenAI-compatible 真实模型 provider：

- `openai-codex` 调用 `/responses` 形式的 Responses API endpoint。
- `openai-chat` 调用 `/chat/completions` 形式的 Chat Completions endpoint。

两个 provider 都要求模型返回严格 JSON action，然后由 runtime 执行。

不要把密钥提交进仓库。可以用 shell 环境变量或本地 `.env` 配置：

```bash
export OPENAI_API_KEY="<your-api-key>"
export HARNESSCODER_OPENAI_BASE_URL="https://your-openai-compatible-endpoint.example/v1"
export HARNESSCODER_OPENAI_MODEL="your-codex-model-name"

python -m harnesscoder --provider openai-codex "看一下这个 repo 是做什么的"
```

Codex Responses profile 可以通过 `--reasoning-effort` 或 `models.toml` 里的
`reasoning_effort` 设置 runtime 推理强度：

```bash
python -m harnesscoder \
  --provider openai-codex \
  --reasoning-effort high \
  "fix the failing test"
```

合法值是 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`。HarnessCoder 会把
配置值和实际发送值记录到 `run_started` 的 trace metadata，方便 eval matrix
对比 high/xhigh。DeepSeek 这类 Chat Completions profile 不会收到这个字段。

如果 base URL 没有以 `/v1` 结尾，HarnessCoder 会先补 `/v1`，再调用
`/responses` 或 `/chat/completions`。

DeepSeek 可以通过 Chat Completions provider 接入。API key 放在 `.env` 或 shell
环境变量里，在 `models.toml` 里只引用变量名：

```toml
[models.deepseek]
provider = "openai-chat"
model = "deepseek-v4-pro"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"
timeout = 120
max_output_tokens = 2000
```

运行 DeepSeek matrix：

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles hc_bench_oracle,scripted,deepseek \
  --context-mode pack \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-deepseek-matrix.md
```

CLI 从仓库启动时，会自动加载当前目录和 `--cwd` 目录下的 `.env`。如果 shell
里已经有同名环境变量，shell 里的值优先。`OPENAI_MODEL` 也可作为
`HARNESSCODER_OPENAI_MODEL` 的 fallback。

## Trace 形状

每次运行都会写入带 timestamp、run id 和 event type 的事件记录。runtime trace
至少包含：

- `run_started`
- `session_context_loaded`
- `context_packed`
- `model_action`
- `policy_decision`
- `tool_result`
- `test_result`
- `state_updated`
- `checkpoint_created`
- `run_resumed`
- `run_finished`

这些 trace 是 append-only JSONL，后续 replay 和 eval 代码可以直接消费它们，而
不依赖运行时内存状态。

`context_packed` 还会携带 `context_budget`，例如：

```json
{
  "type": "context_packed",
  "context_budget": {
    "version": 2,
    "sections": {
      "task_contract": {"chars": 250, "budget": 2400, "preserved": true},
      "packed_context": {"raw_chars": 21000, "chars": 15900, "budget": 16000, "reduced": true}
    },
    "reduced_sections": ["packed_context"],
    "dropped_blocks": 2
  }
}
```

## 开发过程笔记

[docs/development-process.md](docs/development-process.md) 是持续维护的工程日志：
包括设计决策、真实 provider 集成时遇到的 bug、修复记录，以及面试可讲的技术点。

面试展示材料见 [docs/showcase.md](docs/showcase.md) 和
[docs/architecture.md](docs/architecture.md)。

发布检查见 [docs/release-checklist.md](docs/release-checklist.md) 和
[docs/spec-1.0.0.md](docs/spec-1.0.0.md)。后续版本范围分别记录在
[docs/spec-1.0.1.md](docs/spec-1.0.1.md)、
[docs/spec-1.0.2.md](docs/spec-1.0.2.md)、
[docs/spec-1.1.0.md](docs/spec-1.1.0.md) 和
[docs/spec-1.2.0.md](docs/spec-1.2.0.md)；1.2.1 的 HC-Bench-40、run-control
和 reasoning-strength 范围见
[docs/spec-1.2.1.md](docs/spec-1.2.1.md)；1.3.0 的 durable session 范围见
[docs/spec-1.3.0.md](docs/spec-1.3.0.md)，1.3.1 的 Context Budget v2 范围见
[docs/spec-1.3.1.md](docs/spec-1.3.1.md)，1.3.2 的 context ablation matrix 范围见
[docs/spec-1.3.2.md](docs/spec-1.3.2.md)，1.3.3 的真实模型 eval hygiene 范围见
[docs/spec-1.3.3.md](docs/spec-1.3.3.md)。1.1 的 prompt caching 背景总结见
[docs/blog/claude-code-prompt-caching.md](docs/blog/claude-code-prompt-caching.md)。

## Replay And Eval

Replay 会读取 trace 并重建结构化 summary：

```bash
python -m harnesscoder.replay .harnesscoder/runs/<run_id>/trace.jsonl
python -m harnesscoder --replay .harnesscoder/runs/<run_id>/trace.jsonl
```

Resume 会从 checkpoint 继续一次中断的 run：

```bash
python -m harnesscoder --resume .harnesscoder/runs/<run_id>/checkpoint.json
```

Eval 仍然围绕动态 agent loop 组织：

```text
setup repo -> run agent -> run tests -> collect trace -> score -> report
```

运行本地 smoke eval：

```bash
python -m harnesscoder --eval eval/cases.json
```

运行一个命名 model profile：

```bash
python -m harnesscoder \
  --model-profile scripted \
  --eval eval/cases.json
```

用 OpenAI-compatible 模型运行真实 bugfix loop：

```bash
export OPENAI_API_KEY="<your-api-key>"
export HARNESSCODER_OPENAI_BASE_URL="https://your-openai-compatible-endpoint.example/v1"
export HARNESSCODER_OPENAI_MODEL="your-codex-model-name"

python -m harnesscoder \
  --provider openai-codex \
  --eval eval/bugfix_cases.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/bugfix-demo.md
```

`eval/bugfix_cases.json` 使用 `examples/bugfix_demo/repo` 作为 fixture。eval runner
会先把它复制到隔离的 `.harnesscoder/eval-workspaces/...` 工作区，再让 agent
编辑副本，因此 demo fixture 保持稳定。

运行最小 greenfield loop：

```bash
python -m harnesscoder \
  --provider openai-codex \
  --eval eval/greenfield_cases.json \
  --max-iterations 10 \
  --eval-report .harnesscoder/reports/greenfield-demo.md
```

`eval/greenfield_cases.json` 从 `examples/greenfield_demo/repo` 开始，里面没有应用
代码。agent 需要创建 `math_utils.py` 和 `test_math_utils.py`，通过
`python -m unittest discover`，再通过单独的 verifier。case 也声明了
`allowed_tools` 和 `step_budget`，所以评测合同是结构化的，而不是藏在 prose 里。

用 eval matrix 对比多个 profile：

```bash
cp models.example.toml models.toml
# 本地编辑 models.toml；如果包含私人 endpoint，请不要提交。

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles hc_bench_oracle,scripted,openai_codex,deepseek \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-real-matrix.md
```

matrix report 会比较 pass rate、test pass rate、verifier pass rate、平均工具调用、
重复读取、非法调用、策略拒绝、工具失败、memory/compression 指标、RepoMap
使用/注入指标、context budget reductions、dropped blocks、observation artifact
指标和 failure category。每个 profile/case 仍然保留自己的 trace 和 artifact 目录。
如果真实模型 profile 初始化失败，matrix 会记录失败原因，而不是静默跳过。

比较 context modes：

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode none \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-none.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-pack.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode memory \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-real-memory.md
```

比较 RepoMap injection：

```bash
python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --repo-map-mode none \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-without-repo-map.md

python -m harnesscoder \
  --model-config models.toml \
  --model-profiles deepseek \
  --context-mode pack \
  --repo-map-mode auto \
  --eval eval/hc_bench_20.json \
  --eval-report .harnesscoder/reports/hc-bench-20-with-repo-map.md
```

运行内置 context ablation matrix：

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --context-ablations \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-context-ablations.md
```

ablation matrix 会在同一批 case 上比较 `full`、`no_repomap`、`no_memory`、
`no_context_compaction` 和 `no_policy_retry`，并报告 pass rate、工具调用、
repeated reads、invalid calls、policy denials、max_iterations、context tokens、
budget reductions、dropped blocks、RepoMap use、first target read step、memory
updates、compression 和 failure breakdown。

用 deterministic local oracle 运行 HC-Bench-20：

```bash
python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_20.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-20-oracle.md
```

HC-Bench-20 是 0.7.0 的面试型 benchmark，包含 20 个本地 case：

- 7 个业务风格 bugfix case。
- 3 个 recovery case，需要先看到失败测试，再做第二次修复。
- 5 个 greenfield case，通过 `write_file` 创建模块和测试。
- 2 个 context case，强调 search-first 和 bounded read。
- 3 个 policy case，覆盖 path traversal、command injection 和危险命令拒绝。

oracle 不是在证明模型智能，而是在证明 harness 自己稳定：fixture isolation、
policy gates、trace metrics、verifier 和 category-level report 都能跑通。真实
provider 可以通过 `--model-profiles` 在同一套 suite 上对比。

生成并运行更难的 heldout HC-Bench-40：

```bash
python scripts/generate_hc_bench_40.py

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_bench_40.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-bench-40-oracle.md
```

HC-Bench-40 保留 HC-Bench-20 原题，方便历史结果继续可比，同时新增 20 个更难的
heldout case：

- 4 个 ProgramBench-style 编程 / 算法修复 case。
- 3 个 parser / 边界条件 recovery case，需要先看到失败测试，再做第二次修复。
- 5 个 greenfield 编程任务，需要创建源码和测试。
- 5 个大上下文定位 case，用于观察 search-first 和 bounded-read 行为。
- 3 个 policy/security case，覆盖 header redaction、shell-safe argv 构造和
  网络下载命令被拒后的恢复。

生成并 sanity-check HC-Train-40：

```bash
python scripts/generate_hc_train_40.py

python -m harnesscoder \
  --provider hc-bench-oracle \
  --eval eval/hc_train_40.json \
  --max-iterations 8 \
  --eval-report .harnesscoder/reports/hc-train-40-oracle.md
```

HC-Train-40 是训练 trace 池，不是最终成绩单。它包含 40 个 synthetic microbenchmark
case：

- 7 个 bugfix case。
- 14 个 context case，要求 search-first、bounded-read 行为。
- 8 个 recovery case，要求观察失败测试并再次 patch。
- 6 个 policy case，覆盖工具拒绝和安全恢复路径。
- 5 个 greenfield case，通过 `write_file` 创建源码和测试。

用 HC-Train-40 收集 teacher/current-policy traces 做后训练；用 HC-Bench-20 做
历史可比结果，用 HC-Bench-40 作为当前更难的 heldout scorecard 做 live model
comparison。

## 近期 TODO

- 改进 TUI 的历史导航和 trace inspection 命令。
- 增加 session-aware eval cases，衡量跨 run 跟进任务质量。
- 在 `replay/` 下增加更丰富的 failure replay fixtures。
- 当 provider 返回 usage data 时，补充 token/cost accounting。
