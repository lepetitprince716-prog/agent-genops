# Contributing

English | [中文](#中文)

Open an issue before a substantial change. Keep pull requests focused.

## Set up once per clone

You need git, and Python 3.9 or later on your `PATH` as `python3`.

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

## Open a pull request

1. Fork the repository and create a branch from `main`.
2. Commit, then run `python3 tools/privacy_scan.py --tracked --history` inside the clone. It must
   end with `privacy_scan: clean`.
3. Push the branch to your fork and open a pull request against `main`.
4. CI runs the same scan with the public rules only (`--no-private --tracked --history`). A
   first-time contributor's run may wait until a maintainer approves it.

Fixing problems before a push:

- Wrong email in commits you have not pushed: set `user.email`, then run
  `git commit --amend --reset-author --no-edit` for the last commit, or
  `git rebase -r main --exec 'git commit --amend --reset-author --no-edit'` for every commit on
  your branch. Once pushed, say so in the pull request instead.
- A false positive: an allow entry in your own private rules only silences your local hook, and
  CI still fails. Change `tools/privacy_rules.json` in the pull request and say why, or open an
  issue.
- A finding in history that is not yours: do not rewrite history; report it in the pull request.

## Writing rules

- A rule comes with its reason: the incident, measurement or decision behind it. A rule with no
  recorded reason says so instead of inventing one.
- A number comes with its date, hardware and software version.
- Mark claims that are unverified or stale.
- English and Chinese pages are twins. Change both in the same pull request, or open an issue
  for the other language. The Chinese page is written natively, not translated line by line.
- Plain words. No marketing adjectives, no emoji in headings.

## Code

Standard library first. A new dependency needs a reason in the pull request. Code that talks to
machines takes hosts, paths and credentials from configuration, never from literals.

---

## 中文

较大的改动请先开 issue，pull request 保持聚焦。

### 每个克隆设置一次

需要 git，以及 `PATH` 上名为 `python3` 的 Python 3.9 或更新版本。

1. 打开 hook：`git config core.hooksPath .githooks`。
2. 给这个克隆设置 GitHub 的 noreply 邮箱。你的地址在 GitHub 的 Settings → Emails 里，形如 `<id>+<name>@users.noreply.github.com`。然后运行 `git config user.email "<id>+<name>@users.noreply.github.com"`。身份检查会拒绝其他任何地址。
3. 提交里还会带上 `user.name`。不想让真名出现在公开的历史里，就填 GitHub 账号名。
4. 先读 [PRIVACY.md](PRIVACY.md)。不要加入密钥、私有基础设施细节、个人信息、生成的媒体文件或模型权重。

### hook 的输出怎么看

- `privacy_scan: private rules not loaded (0 rules)`：正常。私有规则文件是维护者用的，贡献者不需要。
- `identity author:1: email -- ...`：按第 2 步设置 `user.email`。
- `identity author:1: lan_hostname -- ...`：git 没设邮箱，用你的机器名猜了一个。按第 2 步设置 `user.email`。
- 有任何命中，提交都会被拦下。命中在提交信息里时，信息还留在 `.git/COMMIT_EDITMSG`，改好再提交一次。

### 开 pull request

1. fork 这个仓库，从 `main` 建一个分支。
2. 提交之后，在克隆里运行 `python3 tools/privacy_scan.py --tracked --history`，最后一行必须是 `privacy_scan: clean`。
3. 把分支推到你的 fork，向 `main` 开 pull request。
4. CI 只用公开规则跑同一个扫描（`--no-private --tracked --history`）。第一次贡献时，CI 可能要等维护者批准才会运行。

推送之前遇到问题：

- 还没推送的提交里邮箱写错了：先设置 `user.email`，最后一个提交用 `git commit --amend --reset-author --no-edit`，分支上的所有提交用 `git rebase -r main --exec 'git commit --amend --reset-author --no-edit'`。已经推送了，就在 pull request 里说明。
- 误报：在自己的私有规则里加放行，只能让本地 hook 不报，CI 照样失败。请在 pull request 里修改 `tools/privacy_rules.json` 并写明理由，或者开一个 issue。
- 历史里有不是你造成的命中：不要改写历史，在 pull request 里报告。

### 写作规则

- 规则要附理由：背后的事故、测量或决定。没有记录理由的，就写明没有，不要编。
- 数字要附日期、硬件和软件版本。
- 没核实或已过期的说法要标出来。
- 中英文页面是一对。同一个 pull request 里两边一起改，或者为另一种语言开个 issue。中文页按中文习惯来写，不逐句翻译。
- 用平实的说法，不用营销腔，标题里不放 emoji。

### 代码

优先用标准库。新增依赖要在 pull request 里说明理由。和机器打交道的代码，主机、路径、凭据都从配置里读，不写死在代码里。
