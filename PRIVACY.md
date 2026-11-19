# Privacy

English | [中文](#中文)

This repository is public, and so is every commit in its history. It holds methods, templates
and generic tools. It never holds anything that identifies a person, a machine or a network.

## What never goes in

- IP and MAC addresses, hostnames, tunnel names, domains of private services, private ports.
- Emails, usernames, account handles other than the repo's own, home-directory paths.
- API keys, tokens, cookies, passwords, credential file locations, anything token-shaped.
- Names of private repositories, private tools that reveal infrastructure, personal characters.
- Generated images and videos. They carry the full workflow in their metadata (prompts, paths,
  model files), and they may show things that should stay private.
- Model weights, datasets, ledgers, logs and screenshots of private systems.
- Health or personal details about anyone.

Content that must stay private lives in separate private repositories with their own gates.
Code that is generic by nature (a scanner, a template, an A/B harness with no hostnames) may
move here, after the scan below passes.

## How the guard works

[`tools/privacy_scan.py`](tools/privacy_scan.py) is a standard-library Python scanner. It never
prints a matched value; it prints the rule that fired and where.

- Built-in rules in [`tools/privacy_rules.json`](tools/privacy_rules.json) cover LAN and other
  IP addresses, home paths, Windows user paths, emails, token shapes, MAC addresses, tunnel and
  LAN hostnames, embedded generation metadata in images, and undecodable binaries.
- Your own patterns go in `~/.config/agent-genops/private_rules.json` (same format). That file
  stays on your machine. Set `git config genops.mode maintainer` in your maintainer clone (or set
  `AGENT_GENOPS_REQUIRE_PRIVATE=1`) so the hooks and `./check` fail closed if the private rules
  file is missing, empty, or invalid.
- Git hooks. Each one also runs the Betterleaks wrapper (see the second scan below). Turn them on
  once per clone:
  - `pre-commit` checks your commit identity, the staged files and their names.
  - `commit-msg` checks the message.
  - `pre-push` checks each ref being pushed: the pushed commit and its whole history, every
    historical path, and the target ref name. It only warns when other local refs have findings.
    A push that deletes a remote branch publishes nothing, so the ref name is not checked.
  - In maintainer mode `pre-push` also refuses a remote whose URL is not the registered upstream
    (or the one in `genops.allowedPushUrl`). Contributor mode does not look at the URL.
  - Running `.githooks/pre-push` by hand with no arguments scans the whole history.

```bash
git config core.hooksPath .githooks
```

- Sensitive file paths and ref names that match a rule are replaced with redacted aliases in
  scanner output instead of being printed verbatim. Submodules (`160000`), Git LFS pointers, and
  active `refs/replace/*` entries fail closed.
- CI runs the built-in privacy and Betterleaks scans on every push (branches and tags) and every
  pull request, in jobs separate from the repository's tests. CI never loads maintainer private
  rules.
  - On a push, the scanner, rules and ignore files are the ones in the pushed commit.
  - On a pull request, the scanner, rules, wrapper, template and ignore files are loaded from the
    exact commit of the base branch, never from the pull request. The pull request's own commits
    are then scanned once more with inline allow comments switched off, so a pull request cannot
    exempt its own finding. An exemption that is already in the base branch still applies.
- Commit with a GitHub noreply address; the identity check rejects anything else.
- The hooks and the scanner cover the whole repository, the project folders `cwc/`, `rdbg/` and
  `artfetch/` included. Those folders carry no hooks or scanner of their own.

Run daily or pre-release checks from the repository root:

```bash
./check changed
./check release --to origin --ref refs/heads/main --commit <full-sha>
python3 tools/privacy_scan.py --tracked --history
```

`./check release` is read-only and never pushes: it judges the candidate with the checker and
scanners of the remote's current `main` commit and writes a redacted verification snapshot outside
the repository. [AGENTS.md](AGENTS.md) describes the command and its options.

## Second scan: Betterleaks

Two scanners run side by side. `tools/privacy_scan.py` knows this repository's own rules: addresses,
home paths, emails, hostnames, image metadata, and the private patterns on your machine.
[Betterleaks](https://github.com/betterleaks/betterleaks) is an offline secret scanner with a broad
rule set for provider keys and tokens, and it also looks at entropy. Neither replaces the other; a
change must pass both. Betterleaks never prints a value (`--redact`), a finding is one line,
`rule path:line commit`.

[`tools/secret_scan.sh`](tools/secret_scan.sh) wraps it, and the hooks call it after the privacy scan:

| Hook | Runs | Looks at |
| --- | --- | --- |
| `pre-commit` | `sh tools/secret_scan.sh ignore-check --index`, then `staged` | what the next commit adds |
| `commit-msg` | `sh tools/secret_scan.sh ignore-check --index`, then `message "$1"` | the commit message, every line (`#` lines included) |
| `pre-push` | `sh tools/secret_scan.sh ignore-check <sha>`, then `rev <sha>`, for each pushed ref | the pushed commit and its history, with the commit and tag messages |

Started by hand with no arguments, `pre-push` runs `ignore-check HEAD` and `history` instead, which
covers every commit diff on any ref. [`tools/README.md`](tools/README.md#secret-scan-wrapper) lists
all modes and the exit codes.

Install it once per machine: `brew install betterleaks`, or a release from
https://github.com/betterleaks/betterleaks/releases. Without it on `PATH` the hooks fail (exit 3)
and say so: a guard that skips itself is no guard. CI installs the pinned release 1.10.1, checks its
SHA-256 and runs `sh tools/secret_scan.sh history`; on a pull request it also scans the pull
request's own commits with `range`. A separate job runs all tests of the guard with
`python3 -B -m unittest discover -s tests`, which you can run locally too. Live validation is off,
because it would send candidates to the network, and the repository's own Betterleaks config is not
loaded.

A false positive, checked on 1.10.1:

- Put `betterleaks:allow` (or `gitleaks:allow`) in a comment on the same line. This also works for a
  commit message line.
- Or list its fingerprint, one per line, in `.betterleaksignore` at the repository root. There are
  two forms, both built from the finding line. `path:rule:line` allows that finding in the staged
  files and in every commit of history. `commit:path:rule:line` (the full commit hash from the
  finding line) allows it in that one commit. The file is committed, so the exception is reviewed.
- Neither works for content git treats as binary (a NUL byte in its first 8000 bytes, or `binary`
  or `-diff` in any attributes file git reads). Betterleaks skips such content, so the wrapper
  reads it again through stdin, where a finding has no path and its line is counted among other
  files: a `:rule:line` fingerprint there could cover a token in another file. No ignore file and
  no inline comment applies to that reading. A false positive in binary content is fixed by
  changing the file.
- The three hooks refuse when `.betterleaksignore` or `.gitleaksignore` in the working tree differs
  from the version in the index (`pre-commit`, `commit-msg`) or in the pushed commit (`pre-push`).
  Stage the ignore file together with the change that needs it. The hooks and `./check changed`
  themselves still honour the working-tree ignore file and inline comments.
- An exemption that a change adds itself does not count where it is judged. In CI on a pull request,
  and in `./check release`, the ignore file comes from the trusted base, and the candidate's own
  commits are scanned again with inline allow comments off. The release check scans the commits
  from the remote's current branch (from the trusted baseline for a new branch) to the candidate.
  A maintainer who accepts such a finding passes `--approve-exemption <commit>:<path>:<rule>:<line>`
  once for each finding to `./check release`, and the manifest lists them. Passing the same flags
  again to `--verify-manifest` is required.
- A secret that sits in an already pushed commit message cannot be allowed with a comment. Revoke
  it, then decide with the owner whether history is rewritten.

## If something leaks

Assume a pushed secret is already copied. Revoke or rotate it first, then remove it from the
tree, then decide with the owner whether history needs rewriting. Record the incident with
[`templates/incident-rule.md`](templates/incident-rule.md) and add a rule so the scanner catches
the same shape next time.

---

## 中文

这个仓库是公开的，提交历史也一样公开。这里只放方法、模板和通用工具，不放任何能认出一个人、一台机器或一个网络的东西。

### 绝不放进来的内容

- IP 和 MAC 地址、主机名、隧道名、私有服务的域名、私有端口。
- 邮箱、用户名、除本仓库账号以外的账号名、用户目录路径。
- API key、token、cookie、密码、凭据文件位置，以及一切长得像密钥的字符串。
- 私有仓库的名字、会暴露基础设施的私有工具名、私人角色。
- 生成的图片和视频。它们的元数据里带着完整的工作流（提示词、路径、模型文件名），画面本身也可能有不该公开的东西。
- 模型权重、数据集、账本、日志，以及私有系统的截图。
- 任何人的健康或个人细节。

必须保密的内容放在单独的私有仓库里，由那边自己的闸门把关。天生通用的代码（扫描器、模板、不含主机名的 A/B 测试工具）可以搬过来，前提是先通过下面的扫描。

### 防护怎么工作

[`tools/privacy_scan.py`](tools/privacy_scan.py) 是一个只用标准库的 Python 扫描器。它从不打印命中的内容，只报告是哪条规则、在哪个位置。

- 内置规则在 [`tools/privacy_rules.json`](tools/privacy_rules.json)，覆盖局域网和其他 IP 地址、用户目录路径、Windows 用户路径、邮箱、密钥形态、MAC 地址、隧道和局域网主机名、图片里嵌的生成参数，以及无法解码的二进制文件。
- 你自己的规则写在 `~/.config/agent-genops/private_rules.json`（格式相同），只留在你的机器上。维护者克隆可设置 `git config genops.mode maintainer`（或设置 `AGENT_GENOPS_REQUIRE_PRIVATE=1`），确保私有规则缺失、为空或损坏时 hook 与 `./check` 直接拒绝而不静默降级。
- git hook：每个 hook 还会运行 Betterleaks 包装脚本（见下面的第二道扫描）。每个克隆打开一次即可（命令见上文英文部分）。
  - `pre-commit` 检查提交身份、暂存的文件和它们的路径名。
  - `commit-msg` 检查提交信息。
  - `pre-push` 对每个被推送的 ref 检查：被推送的提交和它的全部历史、每个历史路径，以及目标 ref 名。本地其他 ref 有命中时只告警，不拦。删除远端分支的推送不发布任何内容，所以不检查 ref 名。
  - 维护者模式下，`pre-push` 还会拒绝 URL 不是登记的上游（或 `genops.allowedPushUrl`）的远端；贡献者模式不看 URL。
  - 不带参数手动运行 `.githooks/pre-push` 时，扫描整个历史。
- 命中规则的文件路径名和 ref 名会以脱敏别名输出，不原样打印。未扫描内容的子模块（`160000`）、Git LFS 指针与 `refs/replace/*` 替换引用会默认拒绝。
- CI 在每次 push（全部分支与标签）和每个 pull request 时用内置公开规则跑隐私与 Betterleaks 扫描，扫描 job 与测试 job 分开运行。CI 永远不加载维护者私有规则。
  - push 事件用被推送的提交自己的扫描器、规则和 ignore 文件。
  - pull request 上，扫描器、规则、包装脚本、模板和 ignore 文件从 base 分支的那个提交精确提取，不用 pull request 自己带的版本。然后再把 pull request 自己的提交关掉行内豁免扫一遍，所以 pull request 没法给自己的命中放行。base 分支里已有的豁免照常生效。
- 提交时请用 GitHub 的 noreply 邮箱，身份检查会拒绝其他地址。
- hook 和扫描器管整个仓库，项目文件夹 `cwc/`、`rdbg/`、`artfetch/` 也包括在内。这些文件夹自己不带 hook 和扫描器。
- 日常开发在仓库根目录运行 `./check changed`，发布前用 `./check release --to origin --ref refs/heads/main --commit <完整SHA>` 生成脱敏清单（只读、绝不执行推送）。发布检查用远端当前 `main` 提交里的检查器和扫描器来判，用法和选项见 [AGENTS.md](AGENTS.md)。

### 第二道扫描：Betterleaks

两个扫描器并行。`tools/privacy_scan.py` 管本仓库自己的规则：地址、用户目录路径、邮箱、主机名、图片元数据，以及你本机的私有规则。[Betterleaks](https://github.com/betterleaks/betterleaks) 是离线的密钥扫描器，内置覆盖各家服务商密钥和令牌的规则集，也看熵值。两者互不替代，一次改动必须同时通过。Betterleaks 从不打印密钥本身（`--redact`），一条命中就是一行 `规则 路径:行号 提交`。

[`tools/secret_scan.sh`](tools/secret_scan.sh) 包装了它，hook 在隐私扫描之后调用：`pre-commit` 先跑 `ignore-check --index`，再跑 `staged`（这次提交新增的内容）；`commit-msg` 先跑 `ignore-check --index`，再跑 `message "$1"`（提交信息的每一行，`#` 开头的也算）；`pre-push` 对每个被推送的 ref 先跑 `ignore-check <sha>`，再跑 `rev <sha>`（被推送的提交和它的历史，加上提交信息和标签信息）。不带参数手动运行 `pre-push` 时，改跑 `ignore-check HEAD` 和 `history`，后者覆盖所有引用上的每个提交 diff。全部模式和退出码见 [`tools/README.md`](tools/README.md#密钥扫描包装脚本)。

每台机器装一次：`brew install betterleaks`，或到 https://github.com/betterleaks/betterleaks/releases 下载。`PATH` 上找不到它时 hook 会失败（退出码 3）并说明原因：找不到工具就放行，等于没有守卫。CI 安装钉死的 1.10.1 发布包，校验 SHA-256，然后跑 `sh tools/secret_scan.sh history`；pull request 上还会用 `range` 扫 pull request 自己的提交。另一个 job 用 `python3 -B -m unittest discover -s tests` 跑防护的全部测试，本地也可以这样跑。在线验证是关着的，因为它会把候选密钥发到外面；仓库自己的 Betterleaks 配置也不会被加载。

误报的放行办法（在 1.10.1 上验证过）：

- 在同一行的注释里写 `betterleaks:allow`（`gitleaks:allow` 也认）。提交信息的行同样适用。
- 或者把指纹逐行写进仓库根目录的 `.betterleaksignore`。有两种写法，都从命中那一行取值：`路径:规则:行号` 对暂存区的文件和历史里的每个提交都放行；`提交:路径:规则:行号`（提交取命中那一行里的完整哈希）只对那一个提交放行。这个文件会被提交，所以例外是过了审的。
- 这两种办法对 git 当作二进制的内容（前 8000 字节里有 NUL 字节，或 git 读到的任一属性文件里标了 `binary`、`-diff`）都不管用。Betterleaks 会跳过这类内容，包装脚本另经 stdin 再读一遍，命中不带路径，行号和别的文件一起数，一条 `:规则:行号` 指纹可能放过另一个文件里的令牌。所以这一遍不认任何 ignore 文件，也不认行内注释。二进制内容里的误报只能改文件本身。
- 工作区里的 `.betterleaksignore` 或 `.gitleaksignore` 和暂存区里的版本（`pre-commit`、`commit-msg`），或被推送提交里的版本（`pre-push`）不一致时，三个 hook 都会拒绝。要把 ignore 文件和需要它的改动一起暂存。hook 和 `./check changed` 自己仍然认工作区里的 ignore 文件和行内豁免。
- 改动自己新加的豁免，在做裁决的地方不算数。pull request 上的 CI 和 `./check release` 的 ignore 文件都取自可信基线，候选自己的提交会关掉行内豁免再扫一遍。发布检查扫的是从远端当前分支（新分支则从可信基线）到候选的那些提交。维护者认可这样的命中时，给 `./check release` 逐条传 `--approve-exemption <提交>:<路径>:<规则>:<行号>`，清单里会列出来；`--verify-manifest` 时必须把同样的参数再传一遍。
- 已经推送出去的提交信息里的密钥无法用注释放行。先吊销，再和仓库主人商量要不要改写历史。

### 万一泄露了

推送出去的密钥，默认已经被人拷走了。先吊销或更换，再从文件里删掉，然后和仓库主人商量要不要改写历史。用 [`templates/incident-rule.md`](templates/incident-rule.md) 记下这次事故，并补一条规则，让扫描器下次能抓住同样的形态。
