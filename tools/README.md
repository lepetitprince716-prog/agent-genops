English | [中文](#中文)

# Tools

- [`privacy_scan.py`](privacy_scan.py): keeps personal data out of this public repository. Standard library only.
- [`secret_scan.sh`](secret_scan.sh): second scan for secrets, a wrapper around the Betterleaks command line, called by the same three hooks. Setup and false positives: [PRIVACY.md](../PRIVACY.md#second-scan-betterleaks).
- [`kernel_classes.py`](kernel_classes.py): splits a profiled render's GPU kernels by tensor-core accumulator type and bounds what a GeForce FP32-accumulate unlock could gain. Standard library only.
- [`gemm_probe.py`](gemm_probe.py): times a model's linear-layer GEMMs per kernel and accumulator under sustained load, with the GPU clock and power. Needs CUDA and torch.

## Privacy guard

`privacy_scan.py` keeps personal data out of this public repository: LAN addresses, home paths, emails, credentials and image-generation metadata. Python 3.9+, standard library only. It never prints a matched value; a finding is one line, `location: rule_id -- why`.

### Set up (once per clone)

```sh
git config core.hooksPath .githooks
git config user.email "<id>+<name>@users.noreply.github.com"   # the hooks reject any other address
python3 tools/privacy_scan.py --tracked --history              # expect: clean
```

The hooks run the scanner like this. `pre-commit` runs `--identity --staged`. `commit-msg` runs `--message "$1"`. `pre-push` runs `--rev <sha> --ref-name <ref>` once for each ref being pushed, and then looks at the other local refs only to warn. A push that deletes a remote ref publishes nothing, so it is not checked. Only a hand run of `.githooks/pre-push` with no arguments, or from a terminal, scans `--history`. Each hook also runs the Betterleaks wrapper; see [PRIVACY.md](../PRIVACY.md#how-the-guard-works).

CI runs `--no-private --tracked --history` on every push and every pull request. On a pull request the scanner and rules come from the base branch commit, not from the pull request.

### Modes

Combine them freely. `PATH` may be a file or a directory (recursive, `.git` skipped).

| Flag | Scans |
| --- | --- |
| `--staged` | the index, content and file names: what the next commit will contain |
| `--unstaged` | working-tree changes relative to the index |
| `--untracked` | untracked files that git does not ignore |
| `--tracked` | every tracked file as it is in the working tree |
| `--history` | everything reachable from any ref: every blob, commit and tag, the file names in every commit, the ref names, nested tags layer by layer, refs that point straight at a tree or a blob, and the author, committer and tagger emails and messages. A `refs/replace` entry is a finding. A shallow clone is an error |
| `--rev COMMIT` | one object and everything it reaches: a commit and its history, an annotated tag layer by layer, a tree or a blob |
| `--range BASE..HEAD` | the commits in a range and their file names |
| `--other-refs-except REV` | local history reachable from the other refs, leaving out the given revs (repeatable); the pre-push hook uses it for its warning |
| `--ref-name REF` | check a target ref name against the rules (repeatable) |
| `--identity` | the email in `GIT_AUTHOR_IDENT` and `GIT_COMMITTER_IDENT` must match `allowed_emails` |
| `--message FILE` | a commit message file; every line is scanned, `#` lines too |
| `--rules FILE` | use another public rules file |
| `--no-private` | do not load the private rules |
| `--require-private` | fail unless non-empty private rules are loaded |
| `--source-labels` | prefix staged, unstaged, untracked and branch findings with their source |
| `--json` | print a redacted JSON report on stdout |
| `--clone-mode` | print `maintainer` or `contributor` and exit; the hooks act on this answer |
| `--redact-stream` | read lines from stdin and print them with sensitive paths redacted |

The clone mode is `maintainer` when `git config genops.mode` is `maintainer` (any letter case) or `AGENT_GENOPS_REQUIRE_PRIVATE=1` is set, and `contributor` when the key is `contributor` or not set. Any other value is refused (exit 2) by the scanner and so by every hook.

Exit status: `0` clean, `1` findings, `2` usage or internal error. Locations look like `docs/a.md:12`, `blob 1a2b3c4d5e6f docs/a.md:12` (history), `commit 1a2b3c4d5e6f author:1` or `message:3` (annotated tags say `tag`), and `identity author:1`. Images report line 1. The guard fails closed: a file it cannot read or decode is a finding.

### Rules

| Rule id | Catches |
| --- | --- |
| `lan_ip` | private, CGNAT (100.64/10) and link-local IPv4; IPv6 unique-local and link-local |
| `ipv4_address` | any other dotted quad; documentation ranges pass |
| `home_path` | `/Users/<name>`, `/home/<name>`, `~<name>/`; placeholders (`you`, `user`, `me`, `example`, `runner`, `shared`) pass |
| `windows_user_path` | `X:\Users\<name>`; `Public`, `Default` and placeholders pass |
| `email` | any address except noreply, `@example.com/org/net` and `git@github.com` |
| `credential_shape` | GitHub, Anthropic, OpenAI-style, Hugging Face, AWS, Slack and Google keys, private key headers, JWTs, and `key = long-token` assignments |
| `mac_address` | six hex pairs joined by `:` or `-` |
| `tunnel_host` | hosts under ts.net, trycloudflare.com, cfargotunnel.com and ngrok |
| `lan_hostname` | `<name>.local`, `.lan`, `.internal`, `.home.arpa` |
| `generation_metadata` | PNG text chunks `prompt`, `workflow`, `parameters`, `Comment`, `Description`, or a ComfyUI graph; raw-byte check for JPEG, WEBP, GIF |
| `binary_not_allowed` | a file with NUL bytes whose suffix is not in `allowed_binary_suffixes`; the rules still read its raw bytes, as they do for a file that is not valid UTF-8 |
| `image_header` | a file with an image suffix that does not start with that format's header (PNG signature, JPEG `FF D8 FF`, `GIF87a`/`GIF89a`, `RIFF`…`WEBP`, ICO `00 00 01 00`) |
| `undecodable` | a file that is not valid UTF-8, a commit message not valid in its encoding (the commit's `encoding` header, `i18n.commitEncoding` for the commit-msg hook, else UTF-8), or a file, PNG chunk or git object that cannot be read or parsed |

Author, committer and tagger emails (`--identity`, `--history`) face a stricter test than `email`: only `allowed_emails` patterns pass.

### Private rules

Your own patterns (names, handles, machine names) live outside the repository in `~/.config/agent-genops/private_rules.json`, or in the file named by `AGENT_GENOPS_PRIVATE_RULES`. The schema is the one in `tools/privacy_rules.json`, and every list is appended to the public one. A line on stderr says how many private rules loaded. `AGENT_GENOPS_REQUIRE_PRIVATE=1` turns a missing file into an error (exit 2).

```json
{
  "version": 1,
  "rules": [{"id": "my_handle", "pattern": "\\bmy-handle\\b", "flags": "i", "why": "account handle"}],
  "allow_literals": ["build-box"],
  "allow_patterns": [],
  "allowed_emails": ["^me@example\\.org$"],
  "allowed_binary_suffixes": []
}
```

`version` is required and `note` is free text that is ignored; any other unknown key is an error, so a typo cannot silently drop rules. `flags` is optional (`i` only). `suffixes` optionally limits a rule to file types such as `[".md"]`. Before a line is matched, every `allow_literals` entry (as a whole token, so `0.0.0.0` never hides a longer address) and every `allow_patterns` match is replaced by spaces. Fix a false positive by adding an entry there, not by weakening the public rules.

### Limits

- Pattern based: base64, URL-encoded or split-up values are not decoded.
- File names and ref names are scanned against the same rules, and a name that matches is printed as a redacted alias. Pixel data is not inspected, so keep generated images out of the repository.
- A PNG's text chunks are decoded and read, and so is every other chunk except the pixel chunks (`IDAT`, `fdAT`): bytes in the pixel chunks are not matched against the rules.
- A hostname with an underscore right in front of it (`_name.local_`, as Markdown emphasis writes it) is not caught by the `lan_hostname` rule.
- JPEG, WEBP and GIF are scanned as raw bytes; a large photo can rarely trip a rule by chance.
- `--history` stops on a shallow clone (exit 2); run `git fetch --unshallow` first.
- With `git commit -v` the diff shown in the editor is part of the message file and is scanned too.

### Secret scan wrapper

`secret_scan.sh` runs Betterleaks with `--redact`, with live validation off, and always with Betterleaks' default rules: it loads neither the repository's own Betterleaks config nor one named in the environment (`BETTERLEAKS_CONFIG`, `GITLEAKS_CONFIG` and their `_TOML` forms are cleared). The default config's path prefilter, which skips whole files by name (image and font suffixes, office documents, lock files, `node_modules` and vendor folders), is replaced with one that skips nothing, so those files are read like any other. A finding is one line, `rule path:line commit`. It takes one mode:

| Mode | Scans |
| --- | --- |
| `staged` | the index; content git treats as binary (a NUL byte, or `-diff` or `binary` in `.gitattributes`), which Betterleaks skips, is read again through stdin, so its findings carry no path and the fingerprint is `:rule:line`; `rev`, `range`, `history` and `files` do the same for the blobs and files they cover |
| `unstaged` | working-tree changes relative to the index, with binary content read again as for `staged` |
| `message FILE` | one commit message file |
| `history` | every object any ref reaches: each commit diff (a merge against its first parent), all commit messages, every tag object layer by layer, and trees or blobs that a ref points at directly |
| `rev OBJECT` | one object and what it reaches, as for `privacy_scan.py --rev` |
| `range BASE..HEAD` | the commits in a range, merges against their first parent, and their messages |
| `files FILE...` | the named working-tree files; symlinks are not followed |
| `ignore-check --index` or `ignore-check OBJECT` | exits 1 unless `.betterleaksignore` and `.gitleaksignore` in the working tree are byte for byte the versions in the index or in the tree of `OBJECT`; a missing file counts as a version |

Exit status: `0` clean, `2` usage error, `3` Betterleaks is missing, anything else is a finding or a Betterleaks failure. The hooks run `ignore-check` before each scan, so a working-tree ignore file that the commit does not carry cannot hide a finding. Environment controls (`SECRET_SCAN_IGNORE_PATH`, `SECRET_SCAN_IGNORE_ALLOW=1`, and the redaction settings) are described in the header of the script.

## Kernel classes

`kernel_classes.py` answers one question: if the half-rate cap on FP32-accumulate tensor math were lifted, how much faster could this render get? The method and the Box B results are on [the performance page](../docs/en/07-performance.md#bounding-a-speed-up-you-cannot-run).

### Run

Trace one warm render with CUDA activity:

```python
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
    render_once()
prof.export_chrome_trace("render.json")
```

```sh
python3 tools/kernel_classes.py render.json --seconds 9.89
python3 tools/kernel_classes.py render.json --seconds 9.89 --off render_fp32acc.json
```

| Flag | Does |
| --- | --- |
| `--seconds T` | the render's timed median. Without it T is the kernel total, which runs a little short of wall time, so the ceiling comes out high |
| `--off TRACE` | the same render traced with FP16 accumulation switched off; adds the s measured on this card |
| `--s S` | a speed-up for the class-A kernels, repeatable; default 1.7 and 2.0 |
| `--lenient` | list kernels no rule matches as class U instead of stopping |
| `--json OUT` | also write the classes, ceilings and every kernel row |

The output gives seconds and share per class, one ceiling per s, and a review list: every A, B and U kernel, plus each C kernel whose name looks like matrix or attention work. Read that list before trusting a ceiling. Exit status: `0` done, `2` usage error, unreadable trace, or kernels no rule matches.

### Rules and limits

- The first match in `RULES` wins. SageAttention's FP8 kernel and comfy-kitchen's CUTLASS GEMMs are decided by a template argument.
- A kernel no rule matches stops the run. Add a rule, or pass `--lenient`; each ceiling is then a range, with U counted as C at the low end and as A at the high end.
- The rules were checked by hand on SDXL, Anima, Qwen-Image 2.1 and MOSS-Image renders under ComfyUI 0.42.1 with torch 2.10.0+cu130 on Windows, where template kernels appear with mangled names. Other stacks, torch.compile output and other attention libraries will need rules of their own.
- It bounds; it does not measure. Convolution and attention are assumed to gain the same s as GEMMs.
- The comfy-kitchen INT8 attention kernel is placed in class B from its name; its source was not read.

## GEMM probe

`gemm_probe.py` times each layer shape with cuBLAS and cuBLASLt at both accumulator types and with a Triton matmul that accumulates in FP16. Each variant runs for `--seconds` (default 2) while nvidia-smi is sampled, so the clock, power and power-cap share are measured under load. It also reports the error against an FP32 product and the kernel names. Needs a CUDA GPU, torch 2.7 or later, nvidia-smi on the PATH, and triton for the Triton variant (`--no-triton` skips it).

```sh
python3 tools/gemm_probe.py                     # the four layers of a 3072-wide DiT block, M = 4352
python3 tools/gemm_probe.py --shape qkv=3072,9216 --m 4352 --m 4160 --out gemm.jsonl
```

- One line per variant on stdout; `--out` appends one JSON record per variant.
- The relative error tells the accumulator: about 3e-3 with FP16 accumulation and 2e-4 with FP32 at K = 3072 for these operands.
- Efficiency is reported on GeForce Ada (SM 8.9) only: TFLOPS against the dense peak at the median sampled clock, 1024 FLOPs per SM per clock with FP16 accumulation and 512 with FP32. A median clock can put a value near 1.0 slightly above it.
- `--smi-index` picks the nvidia-smi GPU; on a multi-GPU box make it match the device torch uses.
- Run it with the GPU otherwise idle: another process on the card changes the clock and the result.
- Run on Box B (RTX 4060 Ti, Windows, torch 2.10.0+cu130, Triton 3.8.0) on 2026-10-29; not run on other cards.

## 中文

- [`privacy_scan.py`](privacy_scan.py)：不让个人信息进这个公开仓库。只用标准库。
- [`secret_scan.sh`](secret_scan.sh)：第二道密钥扫描，包装了 Betterleaks 命令行，由同样三个 hook 调用。安装和误报放行见 [PRIVACY.md](../PRIVACY.md#second-scan-betterleaks)。
- [`kernel_classes.py`](kernel_classes.py)：把一张图剖析出的 GPU 内核按张量核累加类型分类，估出 GeForce 的 FP32 累加解锁最多能快多少。只用标准库。
- [`gemm_probe.py`](gemm_probe.py)：持续满载下，按内核和累加类型给模型线性层的矩阵乘计时，同时记下 GPU 频率和功耗。要 CUDA 和 torch。

### 隐私防护

`privacy_scan.py` 在内容进入公开仓库之前拦下个人信息：内网地址、家目录路径、邮箱、凭据，以及图片里嵌入的生成元数据。只用 Python 3.9+ 标准库。命中的原文永远不会打印，每个问题只有一行：`位置: 规则 id -- 原因`。

#### 初次设置（每个克隆做一次）

```sh
git config core.hooksPath .githooks
git config user.email "<id>+<name>@users.noreply.github.com"   # hook 只放行 noreply 邮箱
python3 tools/privacy_scan.py --tracked --history              # 应当输出 clean
```

hook 这样调用扫描器：`pre-commit` 运行 `--identity --staged`；`commit-msg` 运行 `--message "$1"`；`pre-push` 对每个被推送的 ref 运行一次 `--rev <sha> --ref-name <ref>`，再检查本地其余的 ref，但那一步只告警。删除远端 ref 的推送不发布任何内容，所以不检查。只有不带参数、或在终端里手动运行 `.githooks/pre-push` 时，才会扫 `--history`。每个 hook 还会运行 Betterleaks 包装脚本，见 [PRIVACY.md](../PRIVACY.md#防护怎么工作)。

CI 在每次推送和每个 pull request 时运行 `--no-private --tracked --history`。pull request 上，扫描器和规则取自 base 分支的那个提交，不用 pull request 自己带的版本。

#### 参数

可以任意组合；`PATH` 可以是文件或目录（递归，跳过 `.git`）。

| 参数 | 扫描对象 |
| --- | --- |
| `--staged` | 暂存区的内容和文件名，也就是下一次提交会包含的东西 |
| `--unstaged` | 工作区里相对暂存区有改动的文件 |
| `--untracked` | 没被 git 忽略的未跟踪文件 |
| `--tracked` | 工作区里每个已跟踪的文件 |
| `--history` | 所有 ref 可达的一切：每个 blob、提交和标签，每个提交里的文件名，ref 名，逐层展开的嵌套标签，直接指向 tree 或 blob 的 ref，以及作者、提交者、标签者的邮箱和提交说明。`refs/replace` 里有条目就算一条发现。浅克隆会报错 |
| `--rev COMMIT` | 一个对象和它能到达的一切：一个提交连同它的历史、逐层展开的带注释标签、一个 tree 或 blob |
| `--range BASE..HEAD` | 一个提交区间里的提交和文件名 |
| `--other-refs-except REV` | 其余 ref 可达的本地历史，排除给定的 rev（可重复）；pre-push 用它做告警 |
| `--ref-name REF` | 按规则检查目标 ref 名（可重复） |
| `--identity` | `GIT_AUTHOR_IDENT` 和 `GIT_COMMITTER_IDENT` 里的邮箱必须匹配 `allowed_emails` |
| `--message FILE` | 一个提交说明文件，每一行都扫，`#` 开头的也算 |
| `--rules FILE` | 换用另一份公开规则 |
| `--no-private` | 不加载私有规则 |
| `--require-private` | 没有加载到非空的私有规则就失败 |
| `--source-labels` | 在暂存、未暂存、未跟踪和分支的命中前加上来源标签 |
| `--json` | 在标准输出打印脱敏的 JSON 报告 |
| `--clone-mode` | 打印 `maintainer` 或 `contributor` 然后退出；hook 按这个答案行事 |
| `--redact-stream` | 从标准输入读行，把敏感路径脱敏后打印 |

克隆模式：`git config genops.mode` 的值是 `maintainer`（大小写不限），或设了 `AGENT_GENOPS_REQUIRE_PRIVATE=1`，就是 `maintainer`；值是 `contributor` 或没设，是 `contributor`；其他值扫描器一律拒绝（exit 2），所以每个 hook 都拒绝。

退出码：`0` 干净，`1` 有发现，`2` 用法错误或内部错误。位置写法见上面的英文部分，图片一律报第 1 行。宁可误报也不漏报：读不了或解不开的文件，本身就算一条发现。

#### 规则

| 规则 id | 拦截内容 |
| --- | --- |
| `lan_ip` | 私有、CGNAT（100.64/10）和链路本地的 IPv4；IPv6 唯一本地和链路本地地址 |
| `ipv4_address` | 其他任何点分 IPv4；文档专用网段放行 |
| `home_path` | `/Users/<name>`、`/home/<name>`、`~<name>/`；`you`、`user`、`me`、`example`、`runner`、`shared` 这类占位名放行 |
| `windows_user_path` | `X:\Users\<name>`；`Public`、`Default` 和占位名放行 |
| `email` | 所有邮箱，noreply、`@example.com/org/net` 和 `git@github.com` 除外 |
| `credential_shape` | GitHub、Anthropic、OpenAI 风格、Hugging Face、AWS、Slack、Google 的密钥，私钥头，JWT，以及“密钥名 = 长令牌值”的赋值 |
| `mac_address` | 用 `:` 或 `-` 连接的六组十六进制 |
| `tunnel_host` | ts.net、trycloudflare.com、cfargotunnel.com、ngrok 下的主机名 |
| `lan_hostname` | `<name>.local`、`.lan`、`.internal`、`.home.arpa` |
| `generation_metadata` | PNG 文本块 `prompt`、`workflow`、`parameters`、`Comment`、`Description`，或 ComfyUI 节点图；JPEG、WEBP、GIF 查原始字节 |
| `binary_not_allowed` | 含 NUL 字节、后缀又不在 `allowed_binary_suffixes` 里的文件；规则仍按原始字节读它，不是合法 UTF-8 的文件也一样 |
| `image_header` | 带图片后缀、开头却不是该格式文件头的文件（PNG 签名、JPEG `FF D8 FF`、`GIF87a`/`GIF89a`、`RIFF`…`WEBP`、ICO `00 00 01 00`） |
| `undecodable` | 不是合法 UTF-8 的文件，按自己的编码（提交的 `encoding` 头；commit-msg 钩子看 `i18n.commitEncoding`；都没有就是 UTF-8）解不开的提交说明，或读不了、解析不了的文件、PNG 数据块、git 对象 |

作者、提交者和标签者的邮箱（`--identity`、`--history`）要过更严的一关：只有匹配 `allowed_emails` 的才放行。

#### 私有规则

你自己的规则（姓名、账号、机器名）放在仓库之外的 `~/.config/agent-genops/private_rules.json`，也可以用环境变量 `AGENT_GENOPS_PRIVATE_RULES` 指向别的文件。格式与 `tools/privacy_rules.json` 相同，各个列表接在公开规则后面。stderr 上会有一行告诉你加载了多少条私有规则。设了 `AGENT_GENOPS_REQUIRE_PRIVATE=1`，文件不存在就报错退出（退出码 2）。上面英文部分有一个完整的示例。

`version` 必填，`note` 是会被忽略的备注；其余未知的键一律报错，免得拼错键名悄悄丢掉规则。`flags` 可省略（只支持 `i`）；`suffixes` 可以把一条规则限定在某些文件类型上，例如 `[".md"]`。每行匹配之前，`allow_literals` 里的每一项（按整词匹配，所以 `0.0.0.0` 不会遮住更长的地址）和 `allow_patterns` 的每处命中，都会被替换成等长的空格。遇到误报，往这两处加条目，不要去削弱公开规则。

#### 局限

- 只做模式匹配：base64、URL 编码、被拆开的值都不会解码。
- 文件名和 ref 名也按同一套规则检查，命中的名字以脱敏别名输出。不检查像素数据，所以生成的图片不要放进仓库。
- PNG 的文本块（`tEXt`、`zTXt`、`iTXt`）会解码后读，除像素块（`IDAT`、`fdAT`）以外的其他块也按原始字节读；像素块里的字节不参与规则匹配。
- 下划线紧贴在主机名开头的写法（如 Markdown 强调写成的 `_name.local_`）不会被 `lan_hostname` 规则抓到。
- JPEG、WEBP、GIF 按原始字节扫描，较大的照片偶尔会碰巧触发规则。
- 浅克隆上 `--history` 会直接报错退出（退出码 2），先执行 `git fetch --unshallow`。
- 用 `git commit -v` 时，编辑器里的 diff 也在提交说明文件里，会一起被扫描。

#### 密钥扫描包装脚本

`secret_scan.sh` 用 `--redact` 运行 Betterleaks，关掉在线验证，始终用 Betterleaks 的默认规则：不加载仓库自己的 Betterleaks 配置，也不用环境变量指定的配置（`BETTERLEAKS_CONFIG`、`GITLEAKS_CONFIG` 及其 `_TOML` 形式会被清掉）。默认配置里按文件名整份跳过的路径预过滤（图片和字体后缀、办公文档、lock 文件、`node_modules` 和 vendor 目录等）换成了什么都不跳过的版本，这些文件和别的文件一样读。一条命中就是一行 `规则 路径:行号 提交`。它接受一个模式：

| 模式 | 扫描对象 |
| --- | --- |
| `staged` | 暂存区；git 当作二进制的内容（含 NUL 字节，或 `.gitattributes` 里标了 `-diff`、`binary`）Betterleaks 会跳过，这部分另经 stdin 再读一遍，所以命中不带路径，指纹是 `:规则:行号`；`rev`、`range`、`history`、`files` 对各自覆盖的 blob 和文件同样处理 |
| `unstaged` | 工作区里相对暂存区的改动，二进制内容同 `staged` 再读一遍 |
| `message FILE` | 一个提交说明文件 |
| `history` | 所有 ref 可达的对象：每个提交的 diff（合并提交对照第一个父提交）、全部提交说明、逐层展开的每个标签对象，以及 ref 直接指向的 tree 或 blob |
| `rev OBJECT` | 一个对象和它能到达的一切，与 `privacy_scan.py --rev` 一致 |
| `range BASE..HEAD` | 一个区间里的提交（合并提交对照第一个父提交）和它们的提交说明 |
| `files FILE...` | 指定的工作区文件，不跟随符号链接 |
| `ignore-check --index` 或 `ignore-check OBJECT` | 工作区里的 `.betterleaksignore` 和 `.gitleaksignore` 必须和暂存区里、或 `OBJECT` 的 tree 里的版本逐字节相同，否则退出码为 1；文件不存在也算一个版本 |

退出码：`0` 干净，`2` 用法错误，`3` 找不到 Betterleaks，其余是命中或 Betterleaks 自己失败。hook 在每次扫描之前先跑 `ignore-check`，所以提交里没有的工作区 ignore 文件，不能用来遮住命中。环境变量（`SECRET_SCAN_IGNORE_PATH`、`SECRET_SCAN_IGNORE_ALLOW=1` 和脱敏相关的几个）写在脚本开头的注释里。

### 内核分类

`kernel_classes.py` 只回答一个问题：要是 FP32 累加的张量运算不再限半速，这张图最多能快多少？方法和 Box B 上的结果写在[性能那一页](../docs/zh/07-performance.md#跑不了的提速怎么估上限)。

#### 用法

热态剖析一张图，只录 CUDA 活动：

```python
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
    render_once()
prof.export_chrome_trace("render.json")
```

```sh
python3 tools/kernel_classes.py render.json --seconds 9.89
python3 tools/kernel_classes.py render.json --seconds 9.89 --off render_fp32acc.json
```

| 参数 | 作用 |
| --- | --- |
| `--seconds T` | 这张图的计时中位数。不给就拿内核总时间当 T，它比墙钟时间略短，算出的上限会偏高 |
| `--off TRACE` | 同一张图关掉 FP16 累加后的剖析，用来算本卡实测的 s |
| `--s S` | A 类内核的加速倍数，可以给多个；默认 1.7 和 2.0 |
| `--lenient` | 对不上规则的内核归为 U 类，不直接退出 |
| `--json OUT` | 另外把分类、上限和每个内核写成 JSON |

输出是每类的秒数和占比、每个 s 对应的上限，以及一份待核清单：所有 A、B、U 类内核，加上名字像矩阵乘或注意力的 C 类内核。信上限之前先把这份清单过一遍。退出码：`0` 完成，`2` 用法错误、剖析文件读不了，或者有内核对不上规则。

#### 规则与局限

- `RULES` 里第一条命中的规则说了算。SageAttention 的 FP8 内核和 comfy-kitchen 的 CUTLASS 矩阵乘要看模板参数。
- 对不上规则的内核会让程序停下。要么补一条规则，要么加 `--lenient`；这时每个上限都给一个区间，U 类当 C 类算是下沿，当 A 类算是上沿。
- 规则是在 Windows 上、ComfyUI 0.42.1 加 torch 2.10.0+cu130 跑 SDXL、Anima、Qwen-Image 2.1 和 MOSS-Image 时逐个人工核过的，那里模板内核报的是修饰过的名字。换了环境、用 torch.compile 或别的注意力库，都得自己补规则。
- 它只估上限，不实测。卷积和注意力按矩阵乘的 s 算。
- comfy-kitchen 的 INT8 注意力内核是按名字归进 B 类的，源码没读。

### 矩阵乘探针

`gemm_probe.py` 对每个层形状分别用 cuBLAS 和 cuBLASLt 的两种累加，外加一个 FP16 累加的 Triton 矩阵乘计时。每种做法连续跑 `--seconds` 秒（默认 2），期间采样 nvidia-smi，所以频率、功耗和顶墙比例都是满载时量的。它还报和 FP32 乘积比的误差，以及内核名。要 CUDA 显卡、torch 2.7 以上、PATH 里有 nvidia-smi；Triton 那一档要装 triton（`--no-triton` 跳过）。

```sh
python3 tools/gemm_probe.py                     # 3072 宽 DiT 块的四个层，M = 4352
python3 tools/gemm_probe.py --shape qkv=3072,9216 --m 4352 --m 4160 --out gemm.jsonl
```

- 每种做法在标准输出打一行；`--out` 每种做法追加一条 JSON。
- 看相对误差就知道用的哪种累加：这组操作数在 K = 3072 时，FP16 累加约 3e-3，FP32 累加约 2e-4。
- 只有 GeForce Ada（SM 8.9）报效率：TFLOPS 除以按采样频率中位数算的稠密峰值，FP16 累加每个 SM 每周期 1024 次浮点运算，FP32 累加 512 次。频率取的是中位数，接近 1.0 的值可能略超过 1。
- `--smi-index` 选 nvidia-smi 里的哪块卡；多卡机器上要和 torch 用的那块对上。
- 跑的时候卡上别有别的活：别的进程会改变频率，也改变结果。
- 2026-10-29 在 Box B（RTX 4060 Ti，Windows，torch 2.10.0+cu130，Triton 3.8.0）上跑过；别的卡没跑过。
