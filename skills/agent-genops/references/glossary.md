# Glossary

English | [中文](#中文)

Terms used in this skill and in the repository's docs.

| Term | Meaning |
|---|---|
| owner | The person who owns the machines, the budgets and the taste verdicts. In the docs, "I" is the owner. |
| Controller | The machine that runs the agents. In the reference setup it renders nothing; on a single PC it is also the render box. |
| box, Box A, Box B | A machine that renders with ComfyUI. Box A is the main GPU (quality work, training, and the owner's gaming PC); Box B is the second GPU (drafts, tests, datasets). |
| Linux node | The batch machine of the reference setup. |
| root session | The agent session you talk to. It plans, dispatches, verifies and records. |
| worker | A subagent or another vendor's agent that takes one bounded job and reports back. |
| lane | One job that runs in parallel with others. |
| task packet | The written brief a worker gets: objective, owned paths, checks, and where to write the result. |
| line | A model family together with its recipe and pipeline, for example the quality line. |
| sidecar | A second ComfyUI instance on its own version, listening on loopback only. |
| loopback | Listening on 127.0.0.1, so only the same machine can reach it. |
| probe | A read-only check that a box is reachable, has the models and nodes, and is idle. |
| HOLD | The probe failed: do not dispatch, report it, offer another box. A router signals it with exit code 3. |
| smoke | One image rendered with the exact batch command before the batch is released. |
| lease, reaper | The router keeps a model in VRAM for a while after a render, and an idle reaper frees it later. This replaced freeing VRAM after every image. |
| ledger | An append-only record: one row per paid image, per verdict or per run. |
| gate | A hook or policy that refuses an action. A denied call did not run; never route around it. |
| machine gate | Automated checks that may reject an image (safe-content tagger, defect floor, identity distance). They never rank. |
| owner's decision | The reason given when no single incident or measurement produced a rule: the owner set it as policy. A date says when. |
| Anima, Illustrious, NoobAI | Anime-style image model families used in the reference setup. |
| Buzz, Anlas | The credit units of Civitai and NovelAI. |
| herdr | A terminal multiplexer that runs other agents' CLIs as workers: <https://github.com/herdrdev/herdr>. |
| pi | A coding-agent CLI that herdr starts to run DeepSeek and OpenCode Go models with an effort setting. |
| bd (beads) | A task tracker with claims and handoffs: <https://github.com/gastownhall/beads>. |
| MCP server | A process that gives the agent tools over the Model Context Protocol, for example box status or graph submit. |
| plan mode, advisor tool, Workflow, session cards | Features of Claude Code and the Claude desktop app. Skip the rules about them if your agent has none. |

---

## 中文

本 skill 和仓库文档里用到的词。中文页对同一个东西有几种叫法时，表里一并列出。

| 术语 | 意思 |
|---|---|
| owner、仓库主人 | 拥有机器和预算、做审美判断的人。文档里的「我」指的就是仓库主人。 |
| Controller、控制机 | 跑 agent 的机器。参考环境里它不出图；只有一台电脑时，它同时也是渲染机。 |
| 渲染机、Box A、Box B | 用 ComfyUI 出图的机器。Box A 是主力显卡（质量线、训练，也是仓库主人的游戏电脑）；Box B 是第二张显卡（草稿、测试、数据集）。 |
| Linux 节点 | 参考环境里跑批处理的机器。 |
| 主会话、root | 你正在对话的那个 agent 会话，负责规划、派工、验收和记录。 |
| worker | 接一件边界清楚的活、做完回报的 subagent 或其他厂商的 agent。 |
| lane | 和别的活并行跑的一条任务线。 |
| 任务包 | 交给 worker 的书面说明：目标、负责的路径、验收检查、结果写在哪。 |
| 线（质量线、快线等） | 一个模型家族，加上它的配方和出图流程。 |
| 旁路实例、sidecar | 另开的一个 ComfyUI 实例，用自己的版本，只监听本机。 |
| 回环、只监听本机 | 只在 127.0.0.1 上监听，只有同一台机器能连上。 |
| 探测 | 只读检查：机器连得上、模型和节点都在、队列是空的。 |
| HOLD | 探测没通过：不派活，报告，改用另一台机器。路由脚本用退出码 3 表示。 |
| smoke、冒烟 | 放整批之前，用一模一样的批量命令先出的那一张图。 |
| 租约、回收器 | 出图后路由让模型在显存里留一段时间，空闲回收器之后再释放。它取代了每张图之后都释放显存的旧做法。 |
| 账本 | 只追加的记录：每张付费图、每个评审结论或每次运行一行。 |
| 闸门、闸机 | 拒绝某个操作的 hook 或策略。被拒的调用等于没跑，绝不绕过去。 |
| 机器门 | 可以淘汰图片的自动检查（安全内容标签器、瑕疵下限、身份距离）。它们只淘汰，不排名。 |
| 仓库主人的决定 | 规则不来自某一次事故或测量，而是仓库主人当作策略定下的，理由栏就这样写。日期写的是定下的时间。 |
| Anima、Illustrious、NoobAI | 参考环境里用的几个动漫风格图像模型家族。 |
| Buzz、Anlas | Civitai 和 NovelAI 的点数单位。 |
| herdr | 把其他 agent 的 CLI 当作 worker 来跑的终端多路复用器：<https://github.com/herdrdev/herdr>。 |
| pi | herdr 用来跑 DeepSeek 和 OpenCode Go 模型的编码 agent CLI，可以设 effort。 |
| bd（beads） | 支持认领和交接的任务库：<https://github.com/gastownhall/beads>。 |
| MCP 服务 | 通过 Model Context Protocol 给 agent 提供工具的进程，例如查机器状态、提交工作流。 |
| plan mode、advisor 工具、Workflow、会话卡片 | Claude Code 和 Claude 桌面端的功能。你的 agent 没有这些功能，就跳过相关规则。 |
