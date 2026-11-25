# 仓库索引

[English](INDEX.md) · 中文

Agent runs, ComfyUI generates, you enjoy.

躺好收菜。

| 板块 | 是什么 | 在哪 | 从这里读起 |
|---|---|---|---|
| 说明书 | 完整的方法：24 条规则、架构、派工、出图纪律、调试、性能、库存、记忆 | `docs/zh/`、`docs/en/` | [理念](zh/00-philosophy.md) |
| Skill | 同一套方法的 agent 版，按需加载，可作为 Claude Code 插件安装 | `skills/agent-genops/`、`.claude-plugin/` | [SKILL.md](../skills/agent-genops/SKILL.md) |
| 模板与工作流 | 任务包、交接、模型卡等表单；分档 subagent；三张标准 SDXL 工作流 | `templates/`、`workflows/` | [templates/README.md](../templates/README.md) |
| 三个工具 | `cwc` 编译 ComfyUI 画布，`rdbg` 远程跑 PowerShell，`artfetch` 整理训练图 | `cwc/`、`rdbg/`、`artfetch/` | 各自的 README |
| 护栏 | 隐私扫描、密钥扫描、工作流白名单、发布前核验、git hook、CI | `tools/`、`.githooks/`、`check`、`tests/`、`.github/workflows/` | [PRIVACY.md](../PRIVACY.md)、[AGENTS.md](../AGENTS.md) |

## 说明书

中英各 14 篇，内容对应，中文单独写成。先读理念，再按自己的环境挑着读。

| 页面 | 讲什么 |
|---|---|
| [理念](zh/00-philosophy.md) | 24 条工作规则，分六组，每条带来由 |
| [架构](zh/01-architecture.md) | 控制面和执行面怎么接起来 |
| [环境](zh/02-environment.md) | 参考配置，哪台机器跑什么 |
| [派工](zh/03-dispatch.md) | 什么活交给哪一档模型，任务包怎么写，结果怎么验收 |
| [模型上线](zh/04-model-bringup.md) | 新模型或新运行时，从下载到给出结论 |
| [调试](zh/05-debugging.md) | 症状、可能原因、先查什么，远程 Windows 的坑 |
| [出图纪律](zh/06-render-discipline.md) | smoke、输出隔离、队列、GPU 礼仪、清理 |
| [性能](zh/07-performance.md) | A/B 方法、方差、量化和蒸馏的结论 |
| [库存管理](zh/08-inventory.md) | 模型、LoRA、配方、输出、归档、账本 |
| [服务分工](zh/09-providers.md) | 本地机器、NovelAI、Midjourney、Civitai、GPT Image 怎么选 |
| [提示词与评审](zh/10-prompting-and-review.md) | 各模型的提示词规则、委托写提示词、审美判断 |
| [安全与隐私](zh/11-safety-and-privacy.md) | 出网管控、闸门、密钥、公开和私有的分界 |
| [记忆与交接](zh/12-continuity.md) | 记忆文件、状态快照、交接、任务库 |
| [教训](zh/13-lessons.md) | 带日期的事故，以及它们变成了哪条规则 |

每个任务都走同一个循环：受理、盘点、计划、探测、smoke、运行、验收、记录、清理。流程图在 [README](../README.zh-CN.md#每个任务走的流程)，每一步的停止条件在 SKILL.md 的循环表里。

## Skill

[SKILL.md](../skills/agent-genops/SKILL.md) 是入口：角色表、循环、硬规则、派工分档、何时停下问人。细节在 `references/`，用到哪篇才打开哪篇。安装命令见 [README](../README.zh-CN.md#使用-skill)。

skill 启动时先读本机的 `~/.config/agent-genops/LOCAL.md`，模板是 [LOCAL.example.md](../templates/LOCAL.example.md)。说明书里提到的路由器、模型索引、账本出自作者自己的环境，不随仓库发布；SKILL.md 的角色表写了每个角色要做什么，以及只有一台普通 ComfyUI 时用什么代替。

说明书和 skill 篇目对应，改一边时另一边也要看一眼。

| 说明书 | skill 参考 |
|---|---|
| 理念 | SKILL.md 的硬规则 |
| 架构 | `architecture.md` |
| 派工 | `dispatch.md` |
| 模型上线 | `model-bringup.md` |
| 调试 | `debug.md`、`windows-gpu-box.md` |
| 出图纪律 | `render-discipline.md` |
| 性能 | `perf-ab.md` |
| 库存管理 | `inventory.md` |
| 服务分工 | `providers.md` |
| 提示词与评审 | `prompt-rules.md`、`review-loop.md` |
| 安全与隐私 | `safety.md` |
| 记忆与交接 | `continuity.md` |
| 环境、教训 | 无单独对应；术语表 `glossary.md` 只在 skill 里 |

## 模板与工作流

[templates/](../templates/README.md) 里是复制后填空即用的表单：任务包、交接、记忆条目、出图单、smoke 核对、模型卡、A/B 记录、提示词规则本、事故转规则、`LOCAL.example.md`、`fleet.example.yaml`。

`templates/agents/` 是派工分档对应的七个 worker 角色，从 `haiku-worker` 到 `fact-checker`。每个文件上面是 Claude Code 的 front matter，下面是哪家 agent 都能用的正文指令。用 Claude Code 时复制到 `~/.claude/agents/`，插件不会自动安装；用别的 agent 时，按[那里的 README](../templates/agents/README.md) 给每个角色配模型大小、推理强度和权限。

[workflows/](../workflows/README.md) 是三张最小的 SDXL 工作流：文生图、高清修复、双可选 LoRA。每个目录含手写输入图、`cwc compile` 生成的画布 `*.ui.json` 与 API 版 `*.api.json`，以及写明模型来源、许可和测试情况的 README。每个文件都要过 `tools/workflow_policy.py` 的白名单。

## 三个工具

2026-11-18 起三个工具并入本仓库，各有 README、许可证、测试和 CI，彼此独立。护栏覆盖它们的目录。

| 工具 | 做什么 | 语言 | 子命令 | 读起 |
|---|---|---|---|---|
| `cwc` | 把 ComfyUI API 图编译成分组、排版、原生 reroute 走线的画布，并验证导出结果与输入等价 | Python，仅标准库 | `compile`、`render`、`guide`、`presets`、`node`、`learn` | [README](../cwc/README.zh-CN.md)、[ARCHITECTURE](../cwc/docs/ARCHITECTURE.md) |
| `rdbg` | 经系统 `ssh` 在 Windows 主机上跑 PowerShell，不受本地引号和命令行长度影响 | Rust | `ps`、`doctor`、`comfy` | [README](../rdbg/README.md) |
| `artfetch` | 多来源检索插画，按完成度过滤，跨平台去重，整理成 1536 px JPEG 数据集 | Rust | `status`、`resolve`、`probe`、`fetch`、`stage` | [README](../artfetch/README.md) |

`cwc` 的流水线有两条入口：手写输入图走 normalize、instantiate，已有画布或 PNG 走 ingest，汇合后经过 annotate、layout、route、notes、verify、emit，每一步对应 `cwc/src/cwc/` 下一个目录。`cwc/tools/oracle/` 用真实 ComfyUI 前端测量节点尺寸和导出结果，作为测试基准；`cwc/showcase/` 有三张教学示例；`cwc/skills/` 是教 agent 写 API 图的 skill。

## 护栏

| 部件 | 作用 |
|---|---|
| [privacy_scan.py](../tools/privacy_scan.py) | 扫局域网地址、家目录路径、邮箱、token 形状和出图元数据；私有规则放在仓库外 |
| `tools/secret_scan.sh` | 第二道密钥扫描，包装 Betterleaks |
| [workflow_policy.py](../tools/workflow_policy.py) | `workflows/` 白名单：只许登记过的文件、节点和模型名 |
| `check` | `./check changed` 平时用，扫改动并按路径选测试；`./check release` 由维护者在推送前跑，只读 |
| `.githooks/` | pre-commit、commit-msg、pre-push；克隆后运行 `git config core.hooksPath .githooks` 打开 |
| `tests/` | 护栏自身的测试 |
| `.github/workflows/` | `privacy.yml` 在每次推送和 pull request 都跑；三个工具的 CI 在推送到 `main` 和 pull request 且各自目录改动时跑；`cwc-sweeps.yml` 手动触发 |

`tools/` 里的 `kernel_classes.py` 和 `gemm_probe.py` 是[性能](zh/07-performance.md)篇用到的探针，与护栏无关。

## 怎么串起来

说明书写给人，skill 写给 agent，讲的是同一套规则。skill 读 `LOCAL.md` 认识这台机器，派工时用 `templates/` 的任务包和 subagent，出图时用 `workflows/` 的标准图。

三个工具各管一个环节：`cwc` 把 agent 写的 API 图变成人看得懂的画布，`workflows/` 就是它的产物；`rdbg` 对付[调试](zh/05-debugging.md)篇里远程 Windows 出图机的 PowerShell 问题；`artfetch` 准备 LoRA 或风格训练要用的插画数据集。

护栏覆盖所有目录，每次提交和推送都要过一遍。

## 从哪开始

| 想做的事 | 从这里开始 |
|---|---|
| 弄懂这套方法 | [理念](zh/00-philosophy.md)，再按 [README 的环境表](../README.zh-CN.md#仓库里有什么)往下读 |
| 让自己的 agent 用上 | [README · 使用 skill](../README.zh-CN.md#使用-skill)，然后填 `LOCAL.md` |
| 配分档 worker | [templates/agents/](../templates/agents/README.md)，配合[派工](zh/03-dispatch.md) |
| 直接拖进 ComfyUI 出图 | `workflows/` 里的 `*.ui.json` |
| 把 API 图变成整齐画布 | [cwc 教程](../cwc/showcase/README.zh-CN.md) |
| 排查远程 Windows 机器 | [rdbg](../rdbg/README.md)，配合[调试](zh/05-debugging.md) |
| 准备训练图 | [artfetch](../artfetch/README.md) |
| 提交改动 | 打开 hook，运行 `./check changed`，见 [CONTRIBUTING](../CONTRIBUTING.md) |
| 发布前核验 | [AGENTS.md](../AGENTS.md) 里的 `./check release` |
| 查改了什么 | [CHANGELOG](../CHANGELOG.md) |

README 开头的入门包（`comfy_sweep.py`、两张 moss 工作流、`comfyui-zero-node-pilot` skill）从 [v0.1.0 发布页](https://github.com/lepetitprince716-prog/agent-genops/releases/tag/v0.1.0)下载，不在源码目录里。
