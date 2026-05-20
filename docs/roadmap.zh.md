# HarnessCoder 路线图

HarnessCoder 的路线只围绕一个核心判断：

> 一个本地 coding agent harness，最重要的是让真实仓库任务里的行为可评测、
> 可回放、可恢复、可优化。

所以 1.0 之后也不应该马上扩成多 agent 平台、LangGraph/DAG 框架或 Web UI。
路线重点仍然是把单 agent runtime 的证据链做扎实。

## 当前版本：1.3.2

1.3 保留 1.0 的可展示、可复现基线、1.1 的 prompt-cache-aware 上下文治理、
1.2 的 train/eval 边界，并补上跨 run 跟进任务需要的 durable session。随后
1.3.1/1.3.2 把上下文治理做得更可解释：Context Budget v2 进入 trace，context
ablation matrix 进入 eval report。

- 基于 JSONL trace 的事件化 agent loop。
- 经过策略门控的本地工具。
- checkpoint / resume。
- trace replay 和失败归因。
- HC-Bench-20 fixture-backed benchmark。
- deterministic oracle 和 scripted control profiles。
- 通过 model profiles 运行真实模型 matrix report。
- 通过 context pack、任务内 memory、compression metrics 和轻量 RepoMap 做上下文治理。
- 对大工具输出做 observation artifact 存储，保证上下文受控但审计证据不丢。
- 为每轮模型 prompt 记录 fingerprint、stable-prefix token 估算和 cache-break 指标。
- 增加 HC-Train-40 作为训练 trace 池，并显式标注 split/source。
- 保持 HC-Bench-20 独立，作为当前 heldout-like control suite。
- 增加 HC-Bench-40 作为更难的 heldout scorecard，在不混入 train case 的前提下
  扩展原 20 题。
- 为 CLI/TUI/eval 的运行控制决策保留一个小型 runtime control plane 边界，
  先覆盖 active-run 保护和只读 `/status` / `/trace` 类命令。
- `.harnesscoder/sessions/<session_id>.json` 下的 durable session。
- `session_context_loaded` 和 `context_packed.session_context_injected` trace 证据。
- CLI `--session`，以及 TUI `/session`、`/reset-session`。
- 每个 `context_packed` 事件都记录 Context Budget v2，包括 section 字符数、
  预算、preserved/reduced 标记、dropped blocks 和总预算使用量。
- Replay/report 聚合 context budget reductions 和 dropped blocks。
- 内置 `--context-ablations`，比较 `full`、`no_repomap`、`no_memory`、
  `no_context_compaction` 和 `no_policy_retry`。

### 1.3.x 打磨重点

近期 1.3.x 不继续堆新功能，而是强化证据质量：

- 保持 unit tests 和 HC-Bench-20 oracle 全绿。
- 公开文档不暴露私人 provider 名、私人 endpoint 或本地 secret。
- 真实模型 run 暴露出模糊失败时，继续细化 failure category。
- 每修一个 trace、replay、context、memory、RepoMap 或 artifact 相关 bug，都补一个小回归测试。
- 随着指标增多，保持 matrix report 仍然能读。
- 保留 deterministic baseline，把模型波动和 harness 回归分开。
- 保持 prompt / tool ordering 确定，并在报告里暴露 stable-prefix 变化。
- 保持 Context Budget v2 字段稳定，让 replay 和旧报告在小版本之间可比。
- 保持 HC-Train-40、HC-Bench-20、HC-Bench-40 的 split metadata 清楚，避免训练
  trace 收集和最终评测证据混在一起。
- 把 `/status`、`/trace`、中断/取消、恢复、approval、active-run 保护逐步
  收敛到共享 runtime control 语义里，而不是散落在 UI 分支中。
- 用 HC-Bench-40 做更难的 heldout 对比，同时保留 HC-Bench-20 作为历史可比的
  release/evidence baseline。
- 先补 session-aware eval cases，再声称 durable session 真的提升跨 run 跟进任务。
- 上下文治理相关结论优先来自 context ablation matrix，而不是一次性手工对比。

### Control Plane 边界

Hermes 的 Gateway 设计对 HC 的启发是分层，不是产品形态。HarnessCoder 近期
不做 Telegram、Discord、Email 或 Web gateway。它的本地入口已经够了：

```text
CLI / TUI / Eval
-> run control
-> runner
-> trace/checkpoint
-> replay/eval report
```

run-control 层应该回答这些问题：

- 当前是否已有 active run？
- 运行中哪些命令仍然安全？
- 中断、恢复、approval 应该如何被表达和审计？
- UI 能展示哪些 status/trace 信息，而不让 UI 状态变成隐藏真相？

最终事实仍然是 run trace、checkpoint、replay summary、eval report 和
`RunResult`；control plane 只负责协调入口如何进入 runtime。

## 1.4.0 候选：只读 Reviewer / Explorer Subagent

1.4 可以加入一个小的只读 subagent，但定位是 reviewer/explorer，不是通用多
agent 平台。

范围：

- 只读探索仓库。
- 审阅当前 diff，寻找潜在 bug、缺失测试、策略风险、trace/report 不一致。
- 返回带文件和行号的 findings。
- 把 subagent prompt、finding 和处理结果写入 trace。

验收：

- 默认仍然只有 main agent 可以写文件。
- subagent 结果可以从 run trace 里审计。
- report 能展示某个 finding 是被修复还是被显式忽略。
- 不启用 subagent 时，现有单 agent eval 仍然可比较。

不做：

- 不做自动 worker swarm。
- 不做长期记忆平台。
- 不允许 subagent 隐式改文件。
- 不做 graph / DAG 编排框架。

## 更远方向

这些方向可以之后再做，但必须由 benchmark case 和 replay evidence 推动：

- HC-Bench-40 之后继续扩更大 heldout suite，但前提是新增 case 真的带来不同的
  failure mode 或语言/runtime 覆盖。
- 更接近真实仓库的任务和 targeted verifier。
- 更系统地比较更多仓库、语言和 hidden case 变体里的上下文模式。
- 更好的 replay 查看方式，用来检查 model action、tool result、artifact 和 verifier outcome。
- 面向不同语言 / 构建系统的更稳健 tool policy。
- 可选的本地 CLI 打包发布。

## 长期不优先事项

HarnessCoder 不应优先做：

- Web UI。
- SWE-bench 大规模适配。
- 长期用户记忆。
- 通用 workflow DAG。
- 在单 agent harness 可评测、可审计、可恢复之前，扩成多 agent 平台。
