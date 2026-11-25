# Templates

English | [中文](#中文)

Copy a template, fill the angle-bracket placeholders, delete what does not apply.

| File | Use it when | Explained in |
|---|---|---|
| [task-packet.md](task-packet.md) | Handing a bounded job to a subagent or an external worker | [Dispatch](../docs/en/03-dispatch.md) |
| [handoff.md](handoff.md) | Ending a session and starting a successor | [Continuity](../docs/en/12-continuity.md) |
| [memory-entry.md](memory-entry.md) | Recording one fact an agent should remember | [Continuity](../docs/en/12-continuity.md) |
| [run-order.json](run-order.json) | Writing down a render order before probing and smoking it | [Render discipline](../docs/en/06-render-discipline.md) |
| [smoke-check.md](smoke-check.md) | Checking the one smoke image before releasing a batch | [Render discipline](../docs/en/06-render-discipline.md) |
| [model-card.md](model-card.md) | Recording what a base model is good and bad at, and the adoption verdict | [Model bring-up](../docs/en/04-model-bringup.md) |
| [ab-test.md](ab-test.md) | Writing up a speed or quality comparison | [Performance](../docs/en/07-performance.md) |
| [prompt-rulebook.md](prompt-rulebook.md) | Sending prompt-writing work to another model | [Prompting and review](../docs/en/10-prompting-and-review.md) |
| [incident-rule.md](incident-rule.md) | Turning something that went wrong into a rule | [Lessons](../docs/en/13-lessons.md) |
| [LOCAL.example.md](LOCAL.example.md) | Telling the skill what plays each role on your machine; copy it to `~/.config/agent-genops/LOCAL.md` | [Use the skill](../README.md#use-the-skill) |
| [fleet.example.yaml](fleet.example.yaml) | Describing your machines and ComfyUI instances in detail; LOCAL.md points to it | [Environment](../docs/en/02-environment.md) |
| [agents/](agents/) | The seven worker roles of the tier ladder, ready for Claude Code and usable in any agent | [Dispatch](../docs/en/03-dispatch.md) |

In Claude Code the role files go in `~/.claude/agents/` (or `.claude/agents/` in a project). The
plugin does not install them. For other agents, [agents/README.md](agents/README.md) gives each
role a model size, an effort and an access level.

---

## 中文

复制一份模板，填好尖括号里的占位内容，用不上的部分删掉。

| 文件 | 什么时候用 | 说明在哪 |
|---|---|---|
| [task-packet.md](task-packet.md) | 把一件边界清楚的活交给 subagent 或外部 worker | [派工](../docs/zh/03-dispatch.md) |
| [handoff.md](handoff.md) | 结束一个会话、交给接手的会话 | [记忆与交接](../docs/zh/12-continuity.md) |
| [memory-entry.md](memory-entry.md) | 记下一条 agent 以后要记得的事实 | [记忆与交接](../docs/zh/12-continuity.md) |
| [run-order.json](run-order.json) | 探测和 smoke 之前，先把出图单写下来 | [出图纪律](../docs/zh/06-render-discipline.md) |
| [smoke-check.md](smoke-check.md) | 放整批之前核对那张 smoke 图 | [出图纪律](../docs/zh/06-render-discipline.md) |
| [model-card.md](model-card.md) | 记录一个底模擅长什么、不擅长什么，以及采纳结论 | [模型上线](../docs/zh/04-model-bringup.md) |
| [ab-test.md](ab-test.md) | 写速度或质量对比的记录 | [性能](../docs/zh/07-performance.md) |
| [prompt-rulebook.md](prompt-rulebook.md) | 把写提示词的活交给别的模型 | [提示词与评审](../docs/zh/10-prompting-and-review.md) |
| [incident-rule.md](incident-rule.md) | 把一次出错变成一条规则 | [教训](../docs/zh/13-lessons.md) |
| [LOCAL.example.md](LOCAL.example.md) | 告诉 skill 你的机器上由什么来担任各个角色；复制到 `~/.config/agent-genops/LOCAL.md` | [使用 skill](../README.zh-CN.md#使用-skill) |
| [fleet.example.yaml](fleet.example.yaml) | 详细描述你的机器和 ComfyUI 实例；LOCAL.md 会指向它 | [环境](../docs/zh/02-environment.md) |
| [agents/](agents/) | 分档用的七个 worker 角色，Claude Code 可直接用，其他 agent 照表配置 | [派工](../docs/zh/03-dispatch.md) |

用 Claude Code 时，角色文件放进 `~/.claude/agents/`（或项目里的 `.claude/agents/`），插件不会自动安装它们。用别的 agent 时，按 [agents/README.md](agents/README.md) 给每个角色配模型大小、推理强度和权限。
