# Contributing

English | [中文](#中文)

Open an issue before a substantial change. Keep pull requests focused.

## Set up once per clone

You need git, Python 3.9 or later on your `PATH` as `python3`, and
[Betterleaks](https://github.com/betterleaks/betterleaks/releases) (`brew install betterleaks` on
macOS). The hooks fail closed if Betterleaks is missing.

1. Turn on the hooks: `git config core.hooksPath .githooks`.
2. Set a GitHub noreply address for this clone. GitHub shows yours under Settings → Emails; it
   looks like `<id>+<name>@users.noreply.github.com`. Then run
   `git config user.email "<id>+<name>@users.noreply.github.com"`. The identity check rejects
   every other address.
3. Your commits also carry `user.name`. Use your GitHub handle if you do not want your real name
   in a public history.
4. Read [PRIVACY.md](PRIVACY.md). Do not add secrets, private infrastructure details, personal
   data, generated media or model weights.

## What the hooks print

- `privacy_scan: private rules not loaded (0 rules)`: normal. The private rules file is for the
  maintainer; contributors do not need one.
- `identity author:1: email -- ...`: set `user.email` as in step 2.
- `identity author:1: lan_hostname -- ...`: git has no email set and guessed one from your
  machine's name. Set `user.email` as in step 2.
- Any finding stops the commit. If the finding is in the message, the message is still in
  `.git/COMMIT_EDITMSG`; fix it and commit again.
- A refusal about `.betterleaksignore` or `.gitleaksignore`: the file in your working tree differs
  from the staged version (or from the pushed commit). Stage it, or restore it.

## Contributor mode and maintainer mode

- Contributor mode is the default. You need no private rules. `./check changed` says it is a
  contributor check only and not a release check, and the hooks do not look at the push URL.
- Maintainer mode is for the person who publishes. Turn it on with `git config genops.mode maintainer`
  (any letter case) or `AGENT_GENOPS_REQUIRE_PRIVATE=1`. Any other value is contributor mode. In
  maintainer mode the hooks and `./check` fail instead of degrading: the private rules file must
  exist, be non-empty and be valid, `./check changed` also needs `core.hooksPath` set to `.githooks`
  with all three hooks executable, and `pre-push` refuses a remote that is not the registered
  upstream. [AGENTS.md](AGENTS.md) describes `./check release`, which only a maintainer runs.

## Open a pull request

1. Fork the repository and create a branch from `main`.
2. Run `./check changed` while working. It scans staged, unstaged, untracked and branch changes, then
   runs the tests that the changed paths select. The output has a `SUMMARY` line, a `STATES` line
   with the counts of changed files, a `GUARD CHANGES` list and a `TESTS` table. `GUARD CHANGES`
   names the changed guard files, guard tests and root code that select the guard tests; a path that no longer exists (deleted or renamed away, staged, unstaged or committed on the branch) is marked `(removed)`, any other `(changed)`. The tests
   are chosen by path: a changed Markdown file runs `doc-links`, a change under `workflows/` or to
   the workflow policy runs `workflow-policy` (this one also runs with `--no-tests`; the other
   suites are then marked `NOT RUN`), a guard change runs `guard-tests`, and a change inside a
   project folder runs that project's tests. There is no mode that runs everything: to run all
   guard tests, use `python3 -B -m unittest discover -s tests`. Before pushing, you can also run
   `python3 tools/privacy_scan.py --tracked --history` and `sh tools/secret_scan.sh history`.
3. Push the branch to your fork and open a pull request against `main`.
4. CI runs the privacy and Betterleaks scans with the public rules on every push and pull request.
   On a pull request it uses the base branch's scanner, rules and ignore files, and it scans the
   pull request's own commits again with inline allow comments off. A first-time contributor's run
   may wait until a maintainer approves it.

Fixing problems before a push:

- Wrong email in commits you have not pushed: set `user.email`, then run
  `git commit --amend --reset-author --no-edit` for the last commit, or
  `git rebase -r main --exec 'git commit --amend --reset-author --no-edit'` for every commit on
  your branch. Once pushed, say so in the pull request instead.
- A false positive: an allow entry in your own private rules only silences your local hook, and
  CI still fails. Change `tools/privacy_rules.json` in the pull request and say why, or open an
  issue without pasting sensitive values. For a Betterleaks finding, an inline `betterleaks:allow`
  comment or an entry in `.betterleaksignore` that your pull request adds does not silence CI;
  a maintainer decides, see [PRIVACY.md](PRIVACY.md).
- A finding in history that is not yours: do not rewrite history, and **do not paste matched
  values, secrets, or sensitive file paths into a public pull request or issue**. Notify the
  maintainer privately so it can be verified and handled safely.

## Writing rules

- A rule comes with its reason: the incident, measurement or decision behind it. A rule with no
  recorded reason says so instead of inventing one.
- A number comes with its date, hardware and software version.
- Mark claims that are unverified or stale.
- English and Chinese pages are twins. Change both in the same pull request, or open an issue
  for the other language. The Chinese page is written natively, not translated line by line.
  The project folders (`cwc/`, `rdbg/`, `artfetch/`) are English only.
- Plain words. No marketing adjectives, no emoji in headings.

## Code

Standard library first. A new dependency needs a reason in the pull request. Code that talks to
machines takes hosts, paths and credentials from configuration, never from literals.

The project folders `cwc/`, `rdbg/` and `artfetch/` have their own README with the build and
test commands, run from inside the folder. `cwc/` uses only the Python standard library; the two
Rust projects use crates, and a new crate needs a reason too. A pull request that touches one of
them runs that project's workflow in `.github/workflows/`.

---

## 中文

较大的改动请先开 issue，pull request 保持聚焦。

### 每个克隆设置一次

需要 git、`PATH` 上名为 `python3` 的 Python 3.9 或更新版本，以及
[Betterleaks](https://github.com/betterleaks/betterleaks/releases)（macOS 可用 `brew install betterleaks`）。缺少 Betterleaks 时，hook 会直接拒绝执行。

1. 打开 hook：`git config core.hooksPath .githooks`。
2. 给这个克隆设置 GitHub 的 noreply 邮箱。你的地址在 GitHub 的 Settings → Emails 里，形如 `<id>+<name>@users.noreply.github.com`。然后运行 `git config user.email "<id>+<name>@users.noreply.github.com"`。身份检查会拒绝其他任何地址。
3. 提交里还会带上 `user.name`。不想让真名出现在公开的历史里，就填 GitHub 账号名。
4. 先读 [PRIVACY.md](PRIVACY.md)。不要加入密钥、私有基础设施细节、个人信息、生成的媒体文件或模型权重。

### hook 的输出怎么看

- `privacy_scan: private rules not loaded (0 rules)`：正常。私有规则文件是维护者用的，贡献者不需要。
- `identity author:1: email -- ...`：按第 2 步设置 `user.email`。
- `identity author:1: lan_hostname -- ...`：git 没设邮箱，用你的机器名猜了一个。按第 2 步设置 `user.email`。
- 有任何命中，提交都会被拦下。命中在提交信息里时，信息还留在 `.git/COMMIT_EDITMSG`，改好再提交一次。
- 提示 `.betterleaksignore` 或 `.gitleaksignore` 的拒绝：工作区里的这个文件和暂存区的版本（或被推送的提交）不一致。把它暂存，或者还原。

### 贡献者模式和维护者模式

- 贡献者模式是默认的，不需要私有规则。`./check changed` 会说明这只是贡献者检查、不是发布检查，hook 也不看推送地址。
- 维护者模式给负责发布的人用。用 `git config genops.mode maintainer`（大小写不限）或 `AGENT_GENOPS_REQUIRE_PRIVATE=1` 打开，其他取值一律是贡献者模式。维护者模式下，hook 和 `./check` 出问题就直接失败，不降级：私有规则文件必须存在、非空、格式正确；`./check changed` 还要求 `core.hooksPath` 设为 `.githooks`、三个 hook 都可执行；`pre-push` 会拒绝不是登记上游的远端。`./check release` 只有维护者运行，说明见 [AGENTS.md](AGENTS.md)。

### 开 pull request

1. fork 这个仓库，从 `main` 建一个分支。
2. 开发过程中运行 `./check changed`。它检查暂存、未暂存、未跟踪的文件和分支上的提交，然后跑改动路径选中的测试。输出有一行 `SUMMARY`、一行统计改动文件数的 `STATES`、一份 `GUARD CHANGES` 清单和一张 `TESTS` 表。`GUARD CHANGES` 列出改动了的防护文件、防护测试和根目录代码，正是它们选中了 guard 测试；已经不存在的路径（删除或改名走了，不论暂存、未暂存还是已提交在分支上）标 `(removed)`，其余标 `(changed)`。测试按路径选：改了 Markdown 就跑 `doc-links`；改了 `workflows/` 或工作流策略就跑 `workflow-policy`（这一项连 `--no-tests` 也照跑，其余测试那时标成 `NOT RUN`）；改了防护就跑 `guard-tests`；改了项目文件夹里的内容就跑那个项目的测试。没有“全部跑一遍”的模式：要跑全部防护测试，用 `python3 -B -m unittest discover -s tests`。推送前也可手动跑 `python3 tools/privacy_scan.py --tracked --history` 和 `sh tools/secret_scan.sh history`。
3. 把分支推到你的 fork，向 `main` 开 pull request。
4. CI 在每次 push 和 pull request 时只用公开规则跑隐私与 Betterleaks 扫描。pull request 上用 base 分支的扫描器、规则和 ignore 文件，并把 pull request 自己的提交关掉行内豁免再扫一遍。第一次贡献时，CI 可能要等维护者批准才会运行。

推送之前遇到问题：

- 还没推送的提交里邮箱写错了：先设置 `user.email`，最后一个提交用 `git commit --amend --reset-author --no-edit`，分支上的所有提交用 `git rebase -r main --exec 'git commit --amend --reset-author --no-edit'`。已经推送了，就在 pull request 里说明。
- 误报：在自己的私有规则里加放行，只能让本地 hook 不报，CI 照样失败。请在 pull request 里修改 `tools/privacy_rules.json` 并写明理由，或者开一个不含敏感内容的 issue。Betterleaks 的命中也一样：你的 pull request 自己加的行内 `betterleaks:allow` 注释或 `.betterleaksignore` 条目，都压不住 CI，要由维护者来定，见 [PRIVACY.md](PRIVACY.md)。
- 历史里有不是你造成的命中：不要改写历史，也**不要把命中值、密钥或敏感路径贴到公开 pull request 或 issue 里**；请私下通知维护者核查处理。

### 写作规则

- 规则要附理由：背后的事故、测量或决定。没有记录理由的，就写明没有，不要编。
- 数字要附日期、硬件和软件版本。
- 没核实或已过期的说法要标出来。
- 中英文页面是一对。同一个 pull request 里两边一起改，或者为另一种语言开个 issue。中文页按中文习惯来写，不逐句翻译。项目文件夹（`cwc/`、`rdbg/`、`artfetch/`）只有英文。
- 用平实的说法，不用营销腔，标题里不放 emoji。

### 代码

优先用标准库。新增依赖要在 pull request 里说明理由。和机器打交道的代码，主机、路径、凭据都从配置里读，不写死在代码里。

项目文件夹 `cwc/`、`rdbg/`、`artfetch/` 各有自己的 README，里面写了构建和测试的命令，要在文件夹里面运行。`cwc/` 只用 Python 标准库；两个 Rust 项目用 crate，新增 crate 同样要说明理由。改动涉及某个项目的 pull request，会运行 `.github/workflows/` 里该项目的工作流。
