# agent-genops 仓库索引

[English README](../README.md) · [中文 README](../README.zh-CN.md)

Agents plan, dispatch, verify and record. ComfyUI and cloud services only render.

agent 管事，后端只出图。仓库分五块：

| 板块 | 解决什么问题 | 在哪里 | 从哪个文件读起 |
|---|---|---|---|
| 方法说明书 | 人读的完整方法：24 条规则、架构、派工、出图纪律、调试、性能、盘点、记忆 | `docs/zh/`、`docs/en/` | [理念](zh/00-philosophy.md) |
| Agent skill | 同一套方法压缩成 agent 按需加载的版本，可作为 Claude Code 插件安装 | `skills/agent-genops/`、`.claude-plugin/` | [SKILL.md](../skills/agent-genops/SKILL.md) |
| 可复制的材料 | 任务包、交接、模型卡等模板；subagent 定义；三张标准 SDXL 工作流 | `templates/`、`workflows/` | [templates/README.md](../templates/README.md) |
| 三个独立工具 | `cwc` 编译 ComfyUI 画布；`rdbg` 远程跑 PowerShell；`artfetch` 收集和整理训练图 | `cwc/`、`rdbg/`、`artfetch/` | 各自目录里的 README |
| 护栏 | 隐私扫描、密钥扫描、发布前核验、工作流白名单、git hook 和 CI | `tools/`、`.githooks/`、`check`、`tests/`、`.github/workflows/` | [PRIVACY.md](../PRIVACY.md)、[AGENTS.md](../AGENTS.md) |

## 方法说明书

`docs/zh/` 和 `docs/en/` 各 14 篇，内容一一对应，中文是单独写的而不是逐句翻译。先读理念，再按自己的环境挑着读。

| 页面 | 讲什么 |
|---|---|
| [00 理念](zh/00-philosophy.md) | 24 条工作规则，分六组，每条带来由 |
| [01 架构](zh/01-architecture.md) | 控制平面（agent 所在）和执行平面（出图机、云服务）怎么接起来 |
| [02 环境](zh/02-environment.md) | 参考配置：哪台机器跑什么 |
| [03 派工](zh/03-dispatch.md) | 什么活交给哪一档模型，任务包怎么写，结果怎么验收 |
| [04 模型上线](zh/04-model-bringup.md) | 新模型或新运行时从下载到给出结论的流程 |
| [05 调试](zh/05-debugging.md) | 症状、可能原因、先查什么；远程 Windows 的坑 |
| [06 出图纪律](zh/06-render-discipline.md) | smoke 测试、输出隔离、队列、GPU 礼仪、清理 |
| [07 性能](zh/07-performance.md) | A/B 方法、方差、量化和蒸馏的结论 |
| [08 盘点](zh/08-inventory.md) | 模型、LoRA、配方、输出、归档、账本 |
| [09 服务](zh/09-providers.md) | 本地机器、NovelAI、Midjourney、Civitai、GPT Image 怎么选 |
| [10 提示词与评审](zh/10-prompting-and-review.md) | 各模型的提示词规则、委托写提示词、审美判断的方法 |
| [11 安全与隐私](zh/11-safety-and-privacy.md) | 出网管控、闸门、密钥、公开和私有内容的分界 |
| [12 记忆与交接](zh/12-continuity.md) | 记忆文件、状态快照、交接、任务库 |
| [13 教训](zh/13-lessons.md) | 带日期的事故，以及各自变成了哪条规则 |

每次干活都走同一个循环：受理、盘点、计划、探测、smoke、运行、验收、记录、清理。图和每一步的问题在中文 README 的「每个任务走的流程」一节，每一步的停止条件在 SKILL.md 的循环表里。

## Agent skill

`skills/agent-genops/SKILL.md` 是入口：角色表、循环、硬规则、派工分档、什么时候停下问人。细节放在 `references/` 里，agent 用到哪篇才打开哪篇。`.claude-plugin/` 里的两个 JSON 让整个仓库能当 Claude Code 插件市场用，安装命令在 README 的「使用 skill」一节。

skill 会先读机器上的 `~/.config/agent-genops/LOCAL.md`，模板是 [templates/LOCAL.example.md](../templates/LOCAL.example.md)。说明书里提到的路由器、模型索引、账本等脚本来自作者自己的环境，不在这个仓库里；skill 的角色表写了每个角色要做什么，以及只有一台普通 ComfyUI 时用什么代替。

说明书和 skill 讲的是同一套方法，篇目大致对应如下。改其中一边时，另一边通常也要跟着看一眼。

| 说明书 | skill 里的对应篇 |
|---|---|
| 00 理念 | SKILL.md 的硬规则 |
| 01 架构 | `architecture.md` |
| 03 派工 | `dispatch.md` |
| 04 模型上线 | `model-bringup.md` |
| 05 调试 | `debug.md`、`windows-gpu-box.md` |
| 06 出图纪律 | `render-discipline.md` |
| 07 性能 | `perf-ab.md` |
| 08 盘点 | `inventory.md` |
| 09 服务 | `providers.md` |
| 10 提示词与评审 | `prompt-rules.md`、`review-loop.md` |
| 11 安全与隐私 | `safety.md` |
| 12 记忆与交接 | `continuity.md` |
| 02 环境、13 教训 | 没有单独对应的篇；术语表 `glossary.md` 只在 skill 里有 |

## 可复制的材料

[templates/](../templates/README.md) 放的是复制后填空就能用的文件：任务包、交接、记忆条目、出图单 `run-order.json`、smoke 核对表、模型卡、A/B 记录、提示词规则本、事故转规则、`LOCAL.example.md` 和 `fleet.example.yaml`。`templates/agents/` 是七个 Claude Code subagent 定义（Haiku、Sonnet、Sonnet max、Opus medium、Opus high、计划审阅、事实核查），对应派工那篇的分档；插件不会自动装它们，要自己复制到 `~/.claude/agents/`。这七个文件目前只有 Claude Code 格式，写死了 Claude 的 model id 和工具名；派工篇里用到的 Cursor、DeepSeek 等外部 worker 没有对应模板。

[workflows/](../workflows/README.md) 是三张最小的 SDXL 工作流：文生图、高清修复、带两个可选 LoRA。每个目录里有手写的输入图、`cwc compile` 生成的画布 `*.ui.json` 和 API 版 `*.api.json`，以及一份写明模型来源、许可和测试情况的 README。这里的每个文件都要过 `tools/workflow_policy.py` 的白名单检查。

## 三个独立工具

三个工具在 2026-11-18 从各自的仓库搬进来，各有自己的 README、许可证、测试和 CI，彼此不互相调用。护栏覆盖它们，它们自己不带护栏。

| 工具 | 做什么 | 语言 | 子命令 | 读起 |
|---|---|---|---|---|
| `cwc` | 把扁平的 ComfyUI API 图编译成分好组、排好版、用原生 reroute 走线、并验证导出结果和输入等价的画布 | Python，只用标准库 | `compile`、`render`、`guide`、`presets`、`node`、`learn` | [cwc/README.md](../cwc/README.md)，内部结构看 [cwc/docs/ARCHITECTURE.md](../cwc/docs/ARCHITECTURE.md) |
| `rdbg` | 通过系统自带的 `ssh` 在 Windows 主机上跑 PowerShell，不受本地 shell 引号和命令行长度影响 | Rust | `ps`、`doctor`、`comfy` | [rdbg/README.md](../rdbg/README.md) |
| `artfetch` | 多来源检索插画、按完成度过滤、跨平台去重，并整理成 1536 px 的 JPEG 数据集 | Rust | `status`、`resolve`、`probe`、`fetch`、`stage` | [artfetch/README.md](../artfetch/README.md) |

`cwc` 是三者里最大的一个。它的流水线是 normalize、instantiate、annotate、layout、route、verify、emit，每一步对应 `cwc/src/cwc/` 下的一个目录；`cwc/tools/oracle/` 用真实的 ComfyUI 前端测量节点尺寸和导出结果，作为测试的参照；`cwc/showcase/` 是三张教学示例；`cwc/skills/` 里另有一个教 agent 写 API 图的 skill。

## 护栏

仓库是公开的，护栏保证历史里不出现地址、路径、邮箱、密钥和带出图元数据的文件。

| 部件 | 作用 |
|---|---|
| [tools/privacy_scan.py](../tools/privacy_scan.py) 和 `tools/privacy_rules.json` | 扫局域网地址、家目录路径、邮箱、token 形状和出图元数据；私有规则放在仓库外的 `~/.config/agent-genops/private_rules.json` |
| `tools/secret_scan.sh` | 第二道密钥扫描，包装 Betterleaks |
| [tools/workflow_policy.py](../tools/workflow_policy.py) 和 `workflow_policy.json` | `workflows/` 的白名单：只许登记过的文件、节点和模型名 |
| `check` 和 `tools/release_check.py` | `./check changed` 平时用，扫改动并按路径挑测试；`./check release` 推送前由维护者跑，只读，生成发布清单 |
| `.githooks/` | pre-commit、commit-msg、pre-push 三个 hook 调上面的扫描；克隆后要运行 `git config core.hooksPath .githooks` 打开 |
| `tests/` | 根目录的测试全是护栏的测试，不测说明书，也不测三个工具 |
| `.github/workflows/` | `privacy.yml` 每次推送都扫；`cwc.yml`、`rdbg.yml`、`artfetch.yml` 只在对应目录改动时跑；`cwc-sweeps.yml` 手动触发 |

`tools/` 里另外两个脚本和护栏无关：`kernel_classes.py` 按张量核累加类型给 GPU 内核分类，`gemm_probe.py` 在满载下给矩阵乘计时，都出自性能那篇。

## 它们怎么串起来

方法是中心。说明书写给人，skill 写给 agent，两者讲同一套规则。skill 运行时读 `LOCAL.md` 知道这台机器上谁扮演什么角色，派工时用 `templates/` 里的任务包和 subagent 定义，出图时用 `workflows/` 里的标准图或自己写的图。

三个工具和方法之间目前只有一处写在仓库里的连接：`workflows/` 里的画布是 `cwc compile` 生成的。说明书和 skill 都没有提到这三个工具，它们只出现在 README 的「仓库里有什么」一节。按用途看，`cwc` 对应出图前把 API 图变成人能看懂的画布，`rdbg` 对应调试篇里远程 Windows 出图机的 PowerShell 问题，`artfetch` 对应模型上线和盘点里的训练数据准备；这三条对应是按内容推断的，文档里没有写。

护栏横跨所有板块，每次提交和推送都把全仓库扫一遍，包括三个工具的目录。

## 常见任务从哪里开始

| 想做的事 | 从这里开始 |
|---|---|
| 第一次弄懂这套方法 | [理念](zh/00-philosophy.md)，再看 README 里按环境分的阅读顺序 |
| 让自己的 agent 用上这套方法 | README 的「使用 skill」一节，然后填 `LOCAL.md` |
| 给 agent 配分档的 subagent | `templates/agents/`，再读[派工](zh/03-dispatch.md) |
| 拿到能直接拖进 ComfyUI 的工作流 | `workflows/` 里的 `*.ui.json` |
| 把自己写的 API 图变成整齐的画布 | `cwc/README.md` 的 Quickstart，或 `cwc/showcase/README.md` |
| 在远程 Windows 机器上排查 | `rdbg/README.md`，配合[调试](zh/05-debugging.md) |
| 准备一套训练图 | `artfetch/README.md` |
| 改了东西准备提交 | 打开 hook，运行 `./check changed`；细节在 [CONTRIBUTING.md](../CONTRIBUTING.md) |
| 发布前核验 | [AGENTS.md](../AGENTS.md) 里的 `./check release` |
| 查某天改了什么 | [CHANGELOG.md](../CHANGELOG.md) |

## 仓库里找不到的东西

README 开头的 Starter Pack（`comfy_sweep.py`、`workflows/compiled/` 下的两张 moss 工作流、`comfyui-zero-node-pilot` skill）只在 v0.1.0 发布页的压缩包里，仓库源码里没有。

`cwc/README.md` 的安装命令和 `rdbg/docs/install.md` 的安装脚本仍指向搬家前的独立仓库 `comfyui-workflow-compiler` 和 `rdbg`。

`cwc/src/cwc/notes/` 目前是空目录，画布注释的代码在 `annotate/notes.py` 和 `render/notes.py`；`cwc beautify`、`cwc embed` 等命令在 cwc 的路线图里标为计划中。
