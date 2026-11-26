English | [中文](#中文)

# Tools

- [`privacy_scan.py`](privacy_scan.py): keeps personal data out of this public repository. Standard library only.
- [`secret_scan.sh`](secret_scan.sh): second scan for secrets, a wrapper around the Betterleaks command line, called by the same three hooks. Setup and false positives: [PRIVACY.md](../PRIVACY.md#second-scan-betterleaks).
- [`kernel_classes.py`](kernel_classes.py): splits a profiled render's GPU kernels by tensor-core accumulator type and bounds what a GeForce FP32-accumulate unlock could gain. Standard library only.
- [`gemm_probe.py`](gemm_probe.py): times a model's linear-layer GEMMs per kernel and accumulator under sustained load, with the GPU clock and power. Needs CUDA and torch.
- [`safetensors_prot_read.py`](safetensors_prot_read.py): maps `.safetensors` checkpoints with `MAP_SHARED | PROT_READ` (`ACCESS_READ` on Windows), checks Linux `/proc/self/maps` (`r--s`) and `RssAnon` to prevent copy-on-write RSS bloat and on-disk corruption on unified-memory boxes, and guards PyTorch tensors against in-place writes when `torch` is installed.
- [`comfy_ab_harness.py`](comfy_ab_harness.py): runs interleaved `A-B-A` or `ABBA` ComfyUI benchmarks with warm-up discard, `nvidia-smi` clock/power/throttle sampling, median/IQR summaries, JSONL output, and a fail-closed `--strict-cache` check against cached samplers or asymmetric encoder caching. Standard library only.

## Privacy guard

`privacy_scan.py` keeps personal data out of this public repository: LAN addresses, home paths, emails, credentials and image-generation metadata. Python 3.9+, standard library only. It never prints a matched value; a finding is one line, `location: rule_id -- why`.

### Set up (once per clone)

```sh
git config core.hooksPath .githooks
git config user.email "<id>+<name>@users.noreply.github.com"   # the hooks reject any other address
python3 tools/privacy_scan.py --tracked --history              # expect: clean
```

The hooks run the scanner like this. `pre-commit` runs `--identity --staged`. `commit-msg` runs `--message "$1" --as-committed <file in the git directory>` and hands that file to the secret scan (the whole message file when it comes back empty), so both read only what the commit will keep. `pre-push` runs `--rev <sha> --ref-name <ref>` once for each ref being pushed, and then looks at the other local refs only to warn. A push that deletes a remote ref publishes nothing, so it is not checked. Only a hand run of `.githooks/pre-push` with no arguments, or from a terminal, scans `--history`. Each hook also runs the Betterleaks wrapper; see [PRIVACY.md](../PRIVACY.md#how-the-guard-works).

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
| `--as-committed OUT` | with `--message`, for the commit-msg hook: scan only what git keeps after the hook and write it to OUT (a failed write is exit 2). git cleans up after the hook. With no editor (`GIT_EDITOR=:`), or `commit.cleanup` `verbatim` or `whitespace`, that is every line. Under `strip`, the default with an editor, lines starting with the comment string (`core.commentChar` or `core.commentString`, `#` by default) and everything from the scissors line on are dropped; under `scissors`, only the scissors line and what follows. A comment string of `auto`, or a config git cannot read, keeps every line |
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
- The workflow policy (`tools/workflow_policy.py`) undoes percent-encoding up to four rounds and refuses a string that a fifth round would still change (`over_encoded`); it does not decode HTML entities.
- File names and ref names are scanned against the same rules, and a name that matches is printed as a redacted alias. Pixel data is not inspected, so keep generated images out of the repository.
- A PNG's text chunks are decoded and read, and so is every other chunk except the pixel chunks (`IDAT`, `fdAT`): bytes in the pixel chunks are not matched against the rules.
- A hostname with an underscore right in front of it (`_name.local_`, as Markdown emphasis writes it) is not caught by the `lan_hostname` rule.
- JPEG, WEBP and GIF are scanned as raw bytes; a large photo can rarely trip a rule by chance.
- `--history` stops on a shallow clone (exit 2); run `git fetch --unshallow` first.
- The commit-msg hook cannot see `--cleanup` on the command line. An editor commit with `--cleanup=verbatim` or `--cleanup=whitespace` keeps git's comment lines in the commit, and the hook does not scan them; the pre-push scan reads the stored commit and still refuses them.
- The hook cannot see `-v` either. Under `strip` it takes a scissors line as git's and skips what follows, which git keeps when `-v` was not given; pre-push catches that too. Under `verbatim` or `whitespace` the `-v` diff is scanned, though git drops it.

### Secret scan wrapper

`secret_scan.sh` runs Betterleaks with `--redact`, with live validation off, and always with Betterleaks' default rules: it loads neither the repository's own Betterleaks config nor one named in the environment (`BETTERLEAKS_CONFIG`, `GITLEAKS_CONFIG` and their `_TOML` forms are cleared). The default config's path prefilter, which skips whole files by name (image and font suffixes, office documents, lock files, `node_modules` and vendor folders), is replaced with one that skips nothing, so those files are read like any other. A finding is one line, `rule path:line commit`. It takes one mode:

| Mode | Scans |
| --- | --- |
| `staged` | the index; content git treats as binary (a NUL byte, non-UTF-8 bytes, PNG, or `binary` or `-diff` in any attributes file git reads: `.gitattributes`, `.git/info/attributes`, the user's or the system's), which Betterleaks skips, is read again with raw bytes, printable-byte isolation, and decoded PNG text chunks (`tEXt`/`zTXt`/`iTXt`), giving each finding a stable per-file fingerprint (`path:rule:line`, or `path#png-text:rule:line`); `rev`, `range` and `history` do the same for the blobs their commits add or change with commit-scoped fingerprints (`commit:path:rule:line`), and `files` does the same for named files |
| `unstaged` | working-tree changes relative to the index, with binary content read again as for `staged` |
| `message FILE` | one commit message file (inline `betterleaks:allow` works unless `SECRET_SCAN_IGNORE_ALLOW=1`; `.betterleaksignore` is not applied) |
| `history` | every object any ref reaches: each commit diff (a merge against its first parent), all commit messages (`.git/commit`), every tag object layer by layer (`.git/tag`), and trees or blobs that a ref points at directly (`.git/blob` or tree path) |
| `rev OBJECT` | one object and what it reaches, as for `privacy_scan.py --rev` |
| `range BASE..HEAD` | the commits in a range, merges against their first parent, and their messages |
| `files FILE...` | the named working-tree files; symlinks are not followed (their target text uses `path:rule:line`). Files that Betterleaks' dir mode skips by their head or as binary (PDF, ELF, ZIP, gzip, MZ, PNG and more) are read again through the secondary pass with exact file line numbers and normalized repo-relative paths |
| `ignore-check --index` or `ignore-check OBJECT` | exits 1 unless `.betterleaksignore` and `.gitleaksignore` in the working tree are byte for byte the versions in the index or in the tree of `OBJECT`; a missing file counts as a version |

Exit status: `0` clean, `2` usage error, `3` Betterleaks is missing, anything else is a finding or a Betterleaks failure. The hooks run `ignore-check` before each scan, so a working-tree ignore file that the commit does not carry cannot hide a finding. Environment controls (`SECRET_SCAN_IGNORE_PATH`, `SECRET_SCAN_IGNORE_ALLOW=1`, and the redaction settings) are described in the header of the script.

Limits of the secret scan:

- Bare pathless `:rule:line` entries and unscoped `.git/commit:`, `.git/tag:`, or `.git/blob:` entries in `.betterleaksignore` are never honoured. Binary content never honours inline `betterleaks:allow` comments (use `.betterleaksignore` with the stable per-file or commit-scoped fingerprint).
- Other compressed archive formats besides PNG text chunks (`zTXt` and compressed `iTXt`) are not unpacked: a token inside a compressed ZIP or gzip stream is not found. Corrupted or oversized (>64 MiB) compressed PNG text chunks fail closed.

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

## Read-only safetensors mmap

`safetensors_prot_read.py` maps `.safetensors` and `.sft` checkpoints with `MAP_SHARED | PROT_READ` on POSIX (`ACCESS_READ` on Windows). On unified-memory Linux boxes (`UMA Box`), default `MAP_PRIVATE` (`ACCESS_COPY`) mappings duplicate pages into anonymous memory during CUDA host-to-device copies (`+4.0 GiB RssAnon` measured on a 4 GiB copy vs `+0.02 GiB RssAnon` under `PROT_READ`), while writable `MAP_SHARED` risks silent on-disk checkpoint corruption if a node patches weights in place.

```sh
python3 tools/safetensors_prot_read.py model.safetensors --touch --json
python3 tools/safetensors_prot_read.py model.safetensors --verify-maps --load-torch
```

- Works with the Python standard library alone for header validation, read-only `memoryview` slicing, and Linux `/proc/self/maps` (`r--s`) plus `/proc/self/status` (`RssAnon`, `RssFile`) checks.
- When `torch` is installed, `load_safetensors_prot_read()` wraps CPU tensors in `ReadOnlyMmapTensor` (`__torch_dispatch__`), raising `ProtReadWriteError` on any mutating op (`add_`, `zero_`, `copy_`, `out=`, and views) instead of crashing the process with `SIGSEGV`. Call `copy_on_patch(t)` or `.clone()` before an intentional weight mutation.
- Exit status: `0` clean, `1` `/proc/self/maps` permission or write-guard failure, `2` usage or corrupt header error.

## ComfyUI A/B harness

`comfy_ab_harness.py` runs interleaved `A-B-A` or `ABBA` benchmarks against a ComfyUI HTTP endpoint using the standard library alone. It submits graphs without a `client_id` (see [05-debugging.md](../docs/en/05-debugging.md#rules-for-silent-failures)), discards `--warmup` runs per arm, polls `nvidia-smi` in the background when available, prints median and IQR execution times, and writes JSONL records.

```sh
python3 tools/comfy_ab_harness.py --control ctl.json --candidate cand.json \
  --order aba --a2-seed-offset 100000 --strict-cache --out ab.jsonl
python3 tools/comfy_ab_harness.py --control ctl.json --candidate cand.json --off off.json \
  --order abba --seed 1001 --seed 1002 --seed 1003 --strict-cache
```

- `--strict-cache` fails closed (exit `1`) if ComfyUI's `/history` messages show a cached sampler node (catching the `0.07 s` full-graph cache hit when `A_2` repeats `A_1` with the same seed) or asymmetric text-encoder caching across arms (`~1.4 s` uncached `CLIPTextEncode` on one arm against a cached encoder on the other).
- In `aba` mode, `--a2-seed-offset 100000` keeps `A_1` and `B` on identical seeds for pixel/latent gates while giving `A_2` distinct seeds so the sampler always executes. `abba` alternates arm order across seeds without repeating `(arm, seed)`.
- Exit status: `0` clean, `1` `--strict-cache` integrity failure, `2` usage or HTTP/runtime error.

## 中文

- [`privacy_scan.py`](privacy_scan.py)：不让个人信息进这个公开仓库。只用标准库。
- [`secret_scan.sh`](secret_scan.sh)：第二道密钥扫描，包装了 Betterleaks 命令行，由同样三个 hook 调用。安装和误报放行见 [PRIVACY.md](../PRIVACY.md#second-scan-betterleaks)。
- [`kernel_classes.py`](kernel_classes.py)：把一张图剖析出的 GPU 内核按张量核累加类型分类，估出 GeForce 的 FP32 累加解锁最多能快多少。只用标准库。
- [`gemm_probe.py`](gemm_probe.py)：持续满载下，按内核和累加类型给模型线性层的矩阵乘计时，同时记下 GPU 频率和功耗。要 CUDA 和 torch。
- [`safetensors_prot_read.py`](safetensors_prot_read.py)：用 `MAP_SHARED | PROT_READ`（Windows 上用 `ACCESS_READ`）映射 `.safetensors` 权重，核验 Linux `/proc/self/maps`（`r--s`）与 `RssAnon`，在统一内存机器上消除写时复制内存膨胀，并挡住磁盘静默写坏；装了 `torch` 时启用 `ReadOnlyMmapTensor` 原地写入拦截。
- [`comfy_ab_harness.py`](comfy_ab_harness.py)：用标准库驱动 ComfyUI `A-B-A` / `ABBA` 交替测速，支持丢弃预热轮、后台采样 `nvidia-smi` 频率与功耗墙占比、输出中位数与 IQR 及 JSONL，并通过 `--strict-cache` 拦截采样器命中缓存或文本编码器非对称缓存。

### 隐私防护

`privacy_scan.py` 在内容进入公开仓库之前拦下个人信息：内网地址、家目录路径、邮箱、凭据，以及图片里嵌入的生成元数据。只用 Python 3.9+ 标准库。命中的原文永远不会打印，每个问题只有一行：`位置: 规则 id -- 原因`。

#### 初次设置（每个克隆做一次）

```sh
git config core.hooksPath .githooks
git config user.email "<id>+<name>@users.noreply.github.com"   # hook 只放行 noreply 邮箱
python3 tools/privacy_scan.py --tracked --history              # 应当输出 clean
```

hook 这样调用扫描器：`pre-commit` 运行 `--identity --staged`；`commit-msg` 运行 `--message "$1" --as-committed <git 目录里的一个文件>`，再把这个文件交给密钥扫描（它是空的就改交整个说明文件），两者都只读提交会留下的内容；`pre-push` 对每个被推送的 ref 运行一次 `--rev <sha> --ref-name <ref>`，再检查本地其余的 ref，但那一步只告警。删除远端 ref 的推送不发布任何内容，所以不检查。只有不带参数、或在终端里手动运行 `.githooks/pre-push` 时，才会扫 `--history`。每个 hook 还会运行 Betterleaks 包装脚本，见 [PRIVACY.md](../PRIVACY.md#防护怎么工作)。

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
| `--as-committed OUT` | 和 `--message` 一起用，给 commit-msg 钩子：只扫 git 在钩子之后清理完会留下的内容，并把它写进 OUT（写不进去是退出码 2）。没开编辑器（`GIT_EDITOR=:`），或 `commit.cleanup` 是 `verbatim`、`whitespace` 时，留下的是每一行。`strip`（开编辑器时的默认）去掉以注释字符串（`core.commentChar` 或 `core.commentString`，默认 `#`）开头的行和剪刀线及其后的内容；`scissors` 只去掉剪刀线及其后的内容。注释字符串是 `auto`，或 git 读不出配置时，留下每一行 |
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
- 工作流策略（`tools/workflow_policy.py`）最多解四轮百分号编码，第五轮还会变的字符串直接拒绝（`over_encoded`）；它不解 HTML 实体。
- 文件名和 ref 名也按同一套规则检查，命中的名字以脱敏别名输出。不检查像素数据，所以生成的图片不要放进仓库。
- PNG 的文本块（`tEXt`、`zTXt`、`iTXt`）会解码后读，除像素块（`IDAT`、`fdAT`）以外的其他块也按原始字节读；像素块里的字节不参与规则匹配。
- 下划线紧贴在主机名开头的写法（如 Markdown 强调写成的 `_name.local_`）不会被 `lan_hostname` 规则抓到。
- JPEG、WEBP、GIF 按原始字节扫描，较大的照片偶尔会碰巧触发规则。
- 浅克隆上 `--history` 会直接报错退出（退出码 2），先执行 `git fetch --unshallow`。
- commit-msg 钩子看不到命令行上的 `--cleanup`。编辑器式提交加 `--cleanup=verbatim` 或 `--cleanup=whitespace` 时，git 的注释行会进提交，钩子不扫它们；推送前的扫描读存下来的提交对象，照样会拦。
- 钩子也看不到 `-v`。`strip` 下它把剪刀线当成 git 加的，不扫其后的内容，而没带 `-v` 时 git 会保留这些内容；推送前的扫描同样会拦。`verbatim` 或 `whitespace` 下 `-v` 的 diff 会被扫，尽管 git 会删掉它。

#### 密钥扫描包装脚本

`secret_scan.sh` 用 `--redact` 运行 Betterleaks，关掉在线验证，始终用 Betterleaks 的默认规则：不加载仓库自己的 Betterleaks 配置，也不用环境变量指定的配置（`BETTERLEAKS_CONFIG`、`GITLEAKS_CONFIG` 及其 `_TOML` 形式会被清掉）。默认配置里按文件名整份跳过的路径预过滤（图片和字体后缀、办公文档、lock 文件、`node_modules` 和 vendor 目录等）换成了什么都不跳过的版本，这些文件和别的文件一样读。一条命中就是一行 `规则 路径:行号 提交`。它接受一个模式：

| 模式 | 扫描对象 |
| --- | --- |
| `staged` | 暂存区；git 当作二进制的内容（含 NUL 字节、非合法 UTF-8 字节、PNG，或 git 读到的任一属性文件里标了 `binary`、`-diff`：`.gitattributes`、`.git/info/attributes`、用户级或系统级的属性文件）Betterleaks 会跳过，这部分会按原始字节、隔离非可打印字节后的视图和解码后的 PNG 文本块（`tEXt`/`zTXt`/`iTXt`）再读一遍，每条命中带稳定的按文件指纹（`路径:规则:行号` 或 `路径#png-text:规则:行号`）；`rev`、`range`、`history` 对各自提交新增或改动的 blob 同样处理并带上提交哈希（`提交:路径:规则:行号`），`files` 对指定文件同样处理 |
| `unstaged` | 工作区里相对暂存区的改动，二进制内容同 `staged` 再读一遍 |
| `message FILE` | 一个提交说明文件（除非设了 `SECRET_SCAN_IGNORE_ALLOW=1`，否则认同行 `betterleaks:allow`；不读 `.betterleaksignore`） |
| `history` | 所有 ref 可达的对象：每个提交的 diff（合并提交对照第一个父提交）、全部提交说明（`.git/commit`）、逐层展开的每个标签对象（`.git/tag`），以及 ref 直接指向的 tree 或 blob（`.git/blob` 或 tree 内路径） |
| `rev OBJECT` | 一个对象和它能到达的一切，与 `privacy_scan.py --rev` 一致 |
| `range BASE..HEAD` | 一个区间里的提交（合并提交对照第一个父提交）和它们的提交说明 |
| `files FILE...` | 指定的工作区文件，不跟随符号链接（符号链接目标使用 `路径:规则:行号`）。文件头被 Betterleaks 的 dir 模式认成 PDF、ELF、ZIP、gzip、MZ、PNG 等而跳过的文件，会走二次扫描保留原始行号与仓库相对路径 |
| `ignore-check --index` 或 `ignore-check OBJECT` | 工作区里的 `.betterleaksignore` 和 `.gitleaksignore` 必须和暂存区里、或 `OBJECT` 的 tree 里的版本逐字节相同，否则退出码为 1；文件不存在也算一个版本 |

退出码：`0` 干净，`2` 用法错误，`3` 找不到 Betterleaks，其余是命中或 Betterleaks 自己失败。hook 在每次扫描之前先跑 `ignore-check`，所以提交里没有的工作区 ignore 文件，不能用来遮住命中。环境变量（`SECRET_SCAN_IGNORE_PATH`、`SECRET_SCAN_IGNORE_ALLOW=1` 和脱敏相关的几个）写在脚本开头的注释里。

密钥扫描的局限：

- `.betterleaksignore` 里不带路径的 `:规则:行号` 以及不带对象哈希的 `.git/commit:`、`.git/tag:`、`.git/blob:` 条目在任何模式下都不会生效。二进制内容不认行内 `betterleaks:allow` 注释，误报只能用稳定指纹写进 `.betterleaksignore`。
- 除 PNG 文本块（`zTXt` 和开了压缩的 `iTXt`）之外，其他压缩归档格式不会解包（ZIP、gzip 压缩流里的令牌不会被解出）。损坏或超过 64 MiB 解压上限的 PNG 压缩文本块会直接报错拒绝。

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

### 只读共享权重映射

`safetensors_prot_read.py` 在 POSIX 上固定以 `MAP_SHARED | PROT_READ` 映射 `.safetensors` 与 `.sft` 文件（Windows 上走 `ACCESS_READ`）。在统一内存 Linux 机器（`UMA Box`）上，默认的 `MAP_PRIVATE`（`ACCESS_COPY`）在向 CUDA 拷贝 4 GiB 权重时会触发写时复制，额外多出 `+4.0 GiB RssAnon`（换成 `PROT_READ` 后只有 `+0.02 GiB RssAnon`）；而带写权限的 `MAP_SHARED` 一旦碰到节点原地改权重，就会把磁盘上的 `.safetensors` 原文件静默改坏。

```sh
python3 tools/safetensors_prot_read.py model.safetensors --touch --json
python3 tools/safetensors_prot_read.py model.safetensors --verify-maps --load-torch
```

- 不装 `torch` 也能独立运行，用标准库校验文件头、返回只读 `memoryview` 切片，并在 Linux 上核对 `/proc/self/maps`（严格要求 `r--s`）与 `/proc/self/status`（`RssAnon`、`RssFile`）。
- 环境里有 `torch` 时，`load_safetensors_prot_read()` 把 CPU 张量包进 `ReadOnlyMmapTensor`，拦截所有原地写算子（`add_`、`zero_`、`copy_`、`out=` 以及视图与转置别名）并抛出 `ProtReadWriteError`，避免触发不可恢复的 `SIGSEGV`。确实需要打补丁时先调 `copy_on_patch(t)` 或 `.clone()`。
- 退出码：`0` 正常，`1` 映射权限或写保护校验失败，`2` 参数错误或文件头损坏。

### ComfyUI 交替基准测试器

`comfy_ab_harness.py` 只依赖标准库，向 ComfyUI HTTP 接口提交配对的 API 图谱（`--control`、`--candidate` 及可选 `--off`），不带 `client_id`（见 [05-debugging.md](../docs/zh/05-debugging.md#静默出错的规则)），自动丢弃各臂预热轮，按 `aba` 或 `abba` 交替执行，在后台采样 `nvidia-smi` 频率、功耗与功耗墙占比，汇总中位数与四分位距（IQR），并写出 JSONL。

```sh
python3 tools/comfy_ab_harness.py --control ctl.json --candidate cand.json \
  --order aba --a2-seed-offset 100000 --strict-cache --out ab.jsonl
python3 tools/comfy_ab_harness.py --control ctl.json --candidate cand.json --off off.json \
  --order abba --seed 1001 --seed 1002 --seed 1003 --strict-cache
```

- `--strict-cache` 遇到两类失真直接报错退出（退出码 `1`）：采样器命中执行缓存（例如 `A_2` 跟 `A_1` 用同一组 seed，直接走缓存返回 `0.07 s`），或文本编码器在各臂之间非对称命中缓存（一侧冷跑 `CLIPTextEncode` 多花约 `1.4 s`，另一侧直接读缓存）。
- `aba` 模式下加 `--a2-seed-offset 100000`，既能让 `A_1` 跟 `B` 保持同种子做画质与潜变量比对，又能保证 `A_2` 真跑采样器；`abba` 模式跨种子正反交替各臂顺序，不重复提交同一对 `(arm, seed)`。
- 退出码：`0` 正常，`1` 触发 `--strict-cache` 缓存失真拦截，`2` 参数或接口运行报错。
