# Worker roles

English | [中文](#中文)

Seven worker roles for the tier ladder in [Dispatch](../../docs/en/03-dispatch.md). Each file has
two parts: front matter in Claude Code's format, and plain instructions under it. Apart from one
setup note in `sonnet-worker`, the instructions name no vendor and work as a worker prompt in any
agent.

| Role | Job | Model | Effort | Access |
|---|---|---|---|---|
| `haiku-worker` | Bulk reading, extraction, classification, sweeps, run-and-report | small | medium | read, shell, edit |
| `sonnet-worker` | Research that combines sources, messy extraction, diagnosing a failed run | mid | high | read, shell, edit, web |
| `sonnet-worker-max` | Code for a settled design; long tuning with a clear goal | mid | max | read, shell, edit, web |
| `opus-worker-medium` | The default: ordinary implementation, debugging, investigation | large | medium | read, shell, edit, web |
| `opus-worker-high` | Multi-file work, design judgment, lanes with a contract | large | high | read, shell, edit, web |
| `plan-reviewer` | Independent review of a draft plan | large | medium | read, shell |
| `fact-checker` | Checking claims before a commit or a summary | mid | default | read, shell |

The role names come from the reference setup, where small, mid and large are Claude Haiku, Sonnet
and Opus 5.5. The skill and the docs dispatch by these names, so keep them in any agent.

## Claude Code

Copy the files to `~/.claude/agents/` (or `.claude/agents/` in a project) and start a new session.
Check that your account can use the model in each `model` field; change it if not.

## Other agents

For each role, make a worker, subagent or custom mode in your agent:

1. Name it after the role.
2. Use everything under the front matter as its instructions.
3. Pick the model from the Model column and set the effort if your agent has that setting.
4. Give it only the access in the Access column. `plan-reviewer` and `fact-checker` must stay
   read-only (their `shell` access is only for read-only checks such as running tests or inspecting
   git, enforced by their instructions).

With two models, the small rung gets the cheaper one and mid and large share the stronger one.
With one model, keep all seven roles; they still differ in effort, access and instructions. The
ladder's rule still holds: pick the lowest rung whose failure the root can catch.

`sonnet-worker` starts with a setup note about MCP tool names in Claude Code. Delete it elsewhere.

---

## 中文

[派工](../../docs/zh/03-dispatch.md)篇里分档用的七个 worker 角色。每个文件分两段：上面是 Claude Code 格式的 front matter，下面是正文指令。除了 `sonnet-worker` 里一段设置说明，正文不提任何厂商，在哪家 agent 里都能直接当 worker 的提示词用。

| 角色 | 干什么 | 模型 | 推理强度 | 权限 |
|---|---|---|---|---|
| `haiku-worker` | 批量阅读、抽取、分类、扫描、跑命令报结果 | 小 | medium | 读、shell、改文件 |
| `sonnet-worker` | 要综合多个来源的调研、脏乱输入的抽取、诊断失败的运行 | 中 | high | 读、shell、改文件、联网 |
| `sonnet-worker-max` | 照定好的设计写代码；目标清楚的长时间调优 | 中 | max | 读、shell、改文件、联网 |
| `opus-worker-medium` | 默认档：普通实现、调试、排查 | 大 | medium | 读、shell、改文件、联网 |
| `opus-worker-high` | 多文件改动、设计判断、有契约要守的 lane | 大 | high | 读、shell、改文件、联网 |
| `plan-reviewer` | 独立评审一份计划草案 | 大 | medium | 读、shell |
| `fact-checker` | 提交或写总结前核对各种说法 | 中 | 默认 | 读、shell |

角色名沿用参考环境的叫法，那里的小、中、大分别是 Claude Haiku、Sonnet、Opus 5.5。skill 和说明书按这些名字派活，换了 agent 也别改名。

### 在 Claude Code 中使用

把文件复制到 `~/.claude/agents/`（或项目里的 `.claude/agents/`），开一个新会话。先确认每个 `model` 字段写的模型你的账号能用，不能用就改掉。

### 其他 agent

在你的 agent 里给每个角色建一个 worker、subagent 或自定义模式：

1. 名字用角色名。
2. front matter 下面的全部正文作为它的指令。
3. 按「模型」一列挑模型；agent 有推理强度设置的话，也按表设好。
4. 只给「权限」一列里的权限。`plan-reviewer` 和 `fact-checker` 必须只读（表里的 `shell` 仅用于跑测试、查 git 等只读核验，由正文指令约束）。

只有两个模型时，小档用便宜的那个，中档和大档共用强的那个。只有一个模型时，七个角色照样都建，它们在推理强度、权限和指令上仍然不同。分档的规矩不变：挑主会话还能兜住失败的最低一档。

`sonnet-worker` 开头有一段 Claude Code 里 MCP 工具名的设置说明，在别的 agent 里删掉即可。
