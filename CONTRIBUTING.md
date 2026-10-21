# Contributing

English | [中文](#中文)

Open an issue before a substantial change. Keep pull requests focused.

## Before you commit

1. Turn on the hooks once per clone: `git config core.hooksPath .githooks`.
2. Commit with your GitHub noreply address. The identity check rejects other emails.
3. Read [PRIVACY.md](PRIVACY.md). Do not add secrets, private infrastructure details, personal
   data, generated media or model weights.
4. Sign off your commits (`git commit -s`). The sign-off certifies, under the Developer
   Certificate of Origin, that you have the right to submit the change under this repository's
   license.

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

### 提交之前

1. 每个克隆打开一次 hook：`git config core.hooksPath .githooks`。
2. 用 GitHub 的 noreply 邮箱提交，身份检查会拒绝其他邮箱。
3. 先读 [PRIVACY.md](PRIVACY.md)。不要加入密钥、私有基础设施细节、个人信息、生成的媒体文件或模型权重。
4. 提交时加 sign-off（`git commit -s`），表示你按 Developer Certificate of Origin 确认自己有权以本仓库的许可提交这些改动。

### 写作规则

- 规则要附理由：背后的事故、测量或决定。没有记录理由的，就写明没有，不要编。
- 数字要附日期、硬件和软件版本。
- 没核实或已过期的说法要标出来。
- 中英文页面是一对。同一个 pull request 里两边一起改，或者为另一种语言开个 issue。中文页按中文习惯来写，不逐句翻译。
- 用平实的说法，不用营销腔，标题里不放 emoji。

### 代码

优先用标准库。新增依赖要在 pull request 里说明理由。和机器打交道的代码，主机、路径、凭据都从配置里读，不写死在代码里。
