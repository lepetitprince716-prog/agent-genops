# Memory entry template

One file per fact or tight topic. The index carries one line per file. See
`docs/en/12-continuity.md` for the rules.

## File

```markdown
---
name: <kebab-case-slug, same as the file name>
description: <the fact itself, plus the incident or number that makes it stick; one line; written in the language queries will use>
metadata:
  type: <feedback | project | reference | user>
---

<Rule or fact in one or two sentences.>

**Why:** <the incident, measurement or decision, with date (YYYY-MM-DD) and cost. If none was
recorded, write "standing rule".>

**How to apply:** <when this matters and what to do; the trigger an agent should recognise.>

**Snapshot:** <state as of YYYY-MM-DD: branch, PR, version, machine state. Check against git or the
live machine before acting on it.>

**Points to:** <authority file or doc that owns the detail, instead of copying it here.>

<!-- Merged from <old-slug-a>, <old-slug-b> (YYYY-MM-DD), if this file absorbed duplicates. -->
```

## Index line

```markdown
- [<Short title>](<slug>.md) - <fact in under ~120 characters; status words like "merged", "pending", "unverified" kept explicit>
```

## Before writing

- [ ] Is this already in a rule file or an authority doc? Then point to it; do not copy.
- [ ] Is there an existing entry on the same topic? Then update or merge it.
- [ ] Does it hold a secret, an address, a hostname or a personal path? Then leave that out.
- [ ] Is every state in it dated?
- [ ] Is it a routing change or a worker retirement? Then it belongs in the global rules too.

## Audit round checklist

- [ ] Merge duplicate entries; note the merged slugs in the surviving file.
- [ ] Rewrite stale entries; mark superseded facts with the date they changed.
- [ ] Fix dangling links in the index.
- [ ] Back up removed or distilled files to a dated folder.
- [ ] Record counts before and after (files, index size).
