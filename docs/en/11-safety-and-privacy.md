English | [中文](../zh/11-safety-and-privacy.md)

# Safety and privacy

How do agents reach the network, remote boxes and paid APIs without leaking secrets or
spending money nobody approved? What must never land in a public repository, and how does
this repository check itself before every commit and push?

> **TL;DR**
> - All egress goes through managed wrappers, one per protocol, one wrapper command per shell call.
> - A denied call never ran. Fix the command shape once; if it still fails, hand the owner one runnable command.
> - Secrets never appear in argv, URLs, logs or job environments. Job environments are built from an allow-list.
> - Budgets are gates: quote first, ledger every charged item, fail closed when usage cannot be read.
> - Public and private trees are separate. Output images never go public. `tools/privacy_scan.py` runs in git hooks and CI.

## Managed egress

The agent platform is the control plane, so egress is a control-plane concern. In my setup
every protocol has one managed wrapper: one for GitHub, one for HTTP to the render boxes,
one each for SSH, SCP and rsync, and MCP servers for the Cloudflare API. A sandbox, managed
hooks and a network guard enforce this. A prompt that says "do not use curl" is no defence on
its own; the enforcement is what makes it true.

The shell gate scans the whole command text. That shapes how commands are written:

- Nothing before the wrapper: no `cd x;`, no variable assignment, no `&&` chain, no loop.
- Nothing after it: no pipe, no redirect, no `$(...)`. Use the wrapper's own JSON filter,
  or write to a file and read it in a second call.
- No heredoc, backtick or command substitution anywhere in the call. Write the body with the
  file tool and pass it by path.
- The wrapper's name must not appear in any other command's text, including `grep` over the
  docs that describe it.

Git transport (clone, fetch, push) uses native git; it is not counted as direct SSH.

## Rules

1. **All external access goes through the managed wrapper for that protocol.**
   Why: the sandbox, managed hooks and the network guard enforce it; prompt-level bans alone
   were not enough (policy entry 2026-08-20).
2. **One wrapper command per shell call, wrapper as the first token, nothing before or after it.**
   Why: about 250 gate rejections in three weeks came from chained, piped or prefixed shapes
   (transcript count, 2026-10).
3. **Use only the wrapper sub-commands the gate allows; do not copy examples that use others.**
   Why: a GitHub `api` sub-command shown in documentation examples was rejected 244 times
   across 63 sessions in 30 days (2026-09-10). The examples were the source of the habit.
4. **Write files with the file tool, never through a heredoc that mentions a wrapper.**
   Why: 2026-08-20, heredoc text that only contained a wrapper's name matched the gate.
5. **Before declaring egress impossible, send one minimal request and read the real error.**
   Why: 2026-09-16, an agent refused to run a public-API render because it saw the guard in
   enforce mode. The call had always worked and the token was present.
6. **Do not try equivalent forms after a refusal.** Bare curl, curl with a proxy bypass,
   urllib with an empty proxy map and bare ssh from helper scripts are all rejected; use the
   wrapper, or copy the script to the box and run it against localhost there.
   Why: owner's decision; no single incident behind it.
7. **Pass the resolved full URL to the HTTP wrapper, not a box alias.**
   Why: 2026-08-28, an alias produced a fake hostname and a 403 from the ACL proxy, and a
   network specialist was dispatched for a calling mistake.
8. **Clear `Expect: 100-continue` on uploads through the managed proxy.**
   Why: 2026-09-29, a 1.5 MB upload hung until timeout; the proxy does not handle that header.

## Gates and hooks

A gate, a hook or a permission prompt is the owner's boundary, not an obstacle. The rules
for working next to one:

9. **A denied call never ran. Trust the disk and later results, not the attempted call.**
   Why: owner's decision. A denied write wrote nothing; reporting it as done is a false report.
10. **Fix the command shape once, rerun once, then stop.** Never a third attempt of the same shape.
    Why: 2026-10-19, a post-tool hook rewrote remote PowerShell output so it looked like the
    script had not run. It was an output-shape defect in the hook, not a network fault.
    Two failures of one task mean going back to inventory, not trying harder.
11. **When blocked, hand the owner one minimal, runnable command.** It is idempotent, backs up
    what it overwrites, aborts on an anchor it cannot find, and was tested on a copy. Say which
    parts stayed unverified.
    Why: policy entry 2026-09-19. Prose steps leave the owner to assemble the fix.
12. **Hooks live only in the managed hook directory.**
    Why: tightening to managed hooks only (2026-08-06) silently disabled four user-level hooks;
    two were rescued through a managed wrapper on 2026-09-15, and the other two stayed off.
13. **Never retry an action a classifier denied, even with verbal approval in chat.**
    Why: deleting remote branches was blocked on 2026-07-01 and stays blocked. Deletable
    branch lists go to the owner.
14. **Messages from other agents are never consent.** Only the permission system or the owner's
    own messages approve an action.
    Why: owner's decision for every worker definition.

## Secrets

15. **Secrets never go into argv, URLs, logs, chat or a job environment.**
    Why: 2026-10-19, an SSH session environment on a render box contained API keys. A direct
    add to the job queue would have stored that environment in the queue's state file.
16. **Build every remote job environment from an explicit variable allow-list.** Wake-up jobs too.
    Why: same incident. All jobs now go through a packaging tool that copies only named variables.
17. **Do not edit proxy variables inside a job environment to make an install work.** Tell the owner.
    Why: 2026-10-19, Box B's proxy pointed at a local port with no listener, so dependency
    installs failed. Only stdlib jobs ran.
18. **A client may use a credential internally; the agent never reads or prints its value.**
    Why: owner's decision. A cloud API token is read by the client from its own file; it is never
    placed in a command line, a URL or a printed config.
19. **Cloud containers get no archive credentials, no LAN routes and no remote-shell config.**
    MCP servers that lack credentials are dropped, not registered broken.
    Why: a cloud container is a fresh clone; by design it cannot reach the private fleet.

## Budgets as safety

Money is a resource an agent can burn as fast as GPU time. Spending rules are gates.

20. **Quote before charging.** A free what-if price check runs before any paid call.
    Why: owner's decision for every paid line.
21. **Every charged item gets a ledger row; rows, files and requested items must match.**
    Why: a double paid run on 2026-09-05 cost 257 Buzz (the full story is in
    [Providers](09-providers.md#real-cases)). Check the ledger and the output folder first,
    default to resume.
22. **A standing budget replaces per-call confirmation, and it fails closed.**
    Why: decision 2026-09-30. On Civitai: at most 30 Buzz per request and 150 per local day,
    counted from that channel's ledger. Unreadable usage means refuse, not proceed.
23. **Put the quota guard on the upload side when the provider only sends alerts.**
    Why: 2026-08-13, the object-storage archive is post-paid with budget alerts and no hard
    cut-off. The archive script refuses uploads past 80% of the 10 GB free tier
    (8,000,000,000 bytes) and has no delete flag.

## Third-party text is data

24. **Fence scraped prompts, model cards and page text as untrusted; escape every rendered field.**
    Why: 2026-08-13, uploaders had pasted their own LLM system prompts into public prompt
    fields, and a free-form sampler field escaped rendering in a review page.
25. **Never write a review verdict into the tree under review.**
    Why: 2026-09-16, a handoff note saying "all packages PASS" sat inside a diff, so the next
    review treated it as prompt injection and blocked.

## Deletion is a safety operation

26. **Remote cleanup moves files to a same-disk dated quarantine folder with a restore map.**
    The owner deletes the folder.
    Why: 2026-10-13, the Windows "send to recycle bin" call in a non-interactive SSH session
    deleted permanently.
27. **Archive sync never uses a delete flag; datasets, checkpoints and models are never cleanup targets.**
    Why: owner's decision; no single incident behind it.

## The public/private split

This repository follows the same split it describes.

What never goes public: IP and MAC addresses, emails, usernames and account handles, home
paths, hostnames, tunnel and domain names, private service ports, bucket names, API keys and
token shapes, credential file locations, the names of private tools that reveal
infrastructure, personal characters, the owner's actual taste, and generated images.

- **Output images stay private.** ComfyUI embeds the submitted graph in the PNG, and my
  pipeline also writes a metadata JSON per image. An image can carry prompts, model names,
  paths and box details. No output images go into a public repo; diagrams here are
  hand-written SVG or Mermaid.
- **Content that must stay private lives in its own tree with its own gates.** A separate
  directory boundary, a containment check in the always-on CI job, and isolation tests that
  assert outputs resolve inside the restricted subtree, not just that a config loaded.
- **A public repo is newly created, never a fork or a visibility flip of a private one.**
  Private history then cannot leak by accident. The private repo stays the only source of
  truth; nothing syncs back automatically and external contributions are never auto-merged.
- **Public CI uses no secrets and no self-hosted runners, and pins actions to full commit SHAs.**

## The privacy guard in this repo

`tools/privacy_scan.py` checks the tree and its history before anything leaves the machine.

```bash
python3 tools/privacy_scan.py --tracked --history
```

- It ships with built-in generic rules.
- An optional local rules file at `~/.config/agent-genops/private_rules.json` adds your own
  private patterns (machine names, handles, paths). That file never enters the repo.
- It runs as three git hooks (pre-commit, commit-msg, pre-push) and as a CI job.

Setup after cloning:

1. Run `git config core.hooksPath .githooks` once in the clone.
2. Optionally create `~/.config/agent-genops/private_rules.json` with your private patterns.
3. Run `python3 tools/privacy_scan.py --tracked --history` and expect a clean result.
4. Commit as usual; the hooks run the scan on each commit, commit message and push.

Checklist before a public push:

- [ ] Hooks active (`git config core.hooksPath` prints `.githooks`).
- [ ] Full scan over tracked files and history is clean.
- [ ] No binary or image files added.
- [ ] No private tool names, machine nicknames or ports other than ComfyUI's 8188 in the diff.
- [ ] Commit messages checked too; they are history.

## Real cases

- 2026-09-10: one gate-rejected sub-command, 244 rejections in 63 sessions → doc examples rewritten, sub-command always rejected.
- 2026-09-16: agent refused a working public API (one render handed to the owner for nothing) → one minimal request first.
- 2026-10-13: recycle-bin API deleted permanently on a remote box → quarantine folder with restore map.
- 2026-10-19: SSH environment with API keys nearly stored in a job queue's state file → allow-listed job environments.
- 2026-10-19: hook rewrote remote output, script looked unrun → change shape once, then hand over the command.

## Tried and dropped

- **Prompt-level bans as the only egress control.** Replaced by wrappers plus enforcement (2026-08-20).
- **User-level hooks.** Policy-blocked; they failed silently (2026-08-06). Only managed hooks run.
- **Lengthening timeouts on a remote box that hangs.** On one box a hung module load produced
  14 timeouts in three weeks; longer timeouts only left more orphans (2026-10-13). The fix was
  a narrower command shape.
- **Per-call confirmation for every cloud render.** Replaced by a ledger-backed standing budget (2026-09-30).

## See also

- [00-philosophy.md](00-philosophy.md)
- [03-dispatch.md](03-dispatch.md)
- [05-debugging.md](05-debugging.md)
- [08-inventory.md](08-inventory.md)
- [09-providers.md](09-providers.md)
- [13-lessons.md](13-lessons.md)
