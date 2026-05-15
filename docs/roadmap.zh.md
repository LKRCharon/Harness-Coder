# HarnessCoder 路线图

HarnessCoder 的路线只围绕一个核心判断：

> 一个本地 coding agent harness，最重要的是让真实仓库任务里的行为可评测、
> 可回放、可恢复、可优化。

所以 1.0 之后也不应该马上扩成多 agent 平台、LangGraph/DAG 框架或 Web UI。
路线重点仍然是把单 agent runtime 的证据链做扎实。

## 当前版本：1.1.x

1.1.x 保留 1.0 的可展示、可复现基线，并加入 prompt-cache-aware 的上下文治理：

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

### 1.1.x 打磨重点

近期 1.1.x 不继续堆新功能，而是强化证据质量：

- 保持 unit tests 和 HC-Bench-20 oracle 全绿。
- 公开文档不暴露私人 provider 名、私人 endpoint 或本地 secret。
- 真实模型 run 暴露出模糊失败时，继续细化 failure category。
- 每修一个 trace、replay、context、memory、RepoMap 或 artifact 相关 bug，都补一个小回归测试。
- 随着指标增多，保持 matrix report 仍然能读。
- 保留 deterministic baseline，把模型波动和 harness 回归分开。
- 保持 prompt / tool ordering 确定，并在报告里暴露 stable-prefix 变化。

## 1.2.0：只读 Reviewer / Explorer Subagent

1.2 可以加入一个小的只读 subagent，但定位是 reviewer/explorer，不是通用多
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

- 更接近真实仓库的任务和 targeted verifier。
- 更系统地比较 `none`、`pack`、`memory`、RepoMap 等上下文模式。
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
