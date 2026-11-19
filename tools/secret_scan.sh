#!/bin/sh
# Second secret scan, next to tools/privacy_scan.py: wraps Betterleaks.
#
#   sh tools/secret_scan.sh staged           the index, as the next commit would contain it
#   sh tools/secret_scan.sh unstaged         working-tree diff relative to the index
#   sh tools/secret_scan.sh message FILE     one commit message file
#   sh tools/secret_scan.sh history          every object any ref reaches: every commit diff
#                                            (merge commits against their first parent), all
#                                            commit messages, every tag object (nested tags
#                                            layer by layer), and trees or blobs a ref or tag
#                                            points at directly
#   sh tools/secret_scan.sh rev OBJECT       one pushed object: a commit and its history, an
#                                            annotated (nested) tag layer by layer plus what it
#                                            ends in, a tree or a blob
#   sh tools/secret_scan.sh range BASE..HEAD commits in a range (merges against their first
#                                            parent), plus their messages
#   sh tools/secret_scan.sh files FILE...    specific working-tree files (symlinks not followed)
#   sh tools/secret_scan.sh ignore-check --index | OBJECT
#                                            exit 1 unless the working tree's .betterleaksignore
#                                            and .gitleaksignore are byte for byte the versions in
#                                            the index or in OBJECT's tree (absent counts as a
#                                            version); the hooks run it before each scan
#
# Betterleaks itself scans diffs only and shows a merge commit no diff, so content that only a
# merge adds would pass unseen; every diff walk here asks git for merges against their first
# parent. Tag objects, messages and directly referenced trees and blobs go through stdin.
#
# Without SECRET_SCAN_IGNORE_PATH, Betterleaks applies the ignore files it finds on disk at the root
# of its source (and, for stdin, in the current directory), whatever the scanned commit holds. A
# hook that scanned with a working-tree copy the commit does not carry would pass content under an
# exemption no reviewer sees; ignore-check is how the hooks refuse that.
#
# Optional environment controls:
#   SECRET_SCAN_IGNORE_PATH   explicit .betterleaksignore/.gitleaksignore file or directory. When
#                             set, it is the only ignore list: Betterleaks runs from an empty
#                             directory, so no .betterleaksignore or .gitleaksignore in the working
#                             tree (tracked, untracked, or checked out from the scanned history)
#                             applies. A path that does not exist is a usage error. The unstaged
#                             mode cannot be isolated from the working tree and refuses it.
#   SECRET_SCAN_IGNORE_ALLOW  when "1", pass --ignore-gitleaks-allow (inline allow comments off)
#   SECRET_SCAN_REDACT_SCANNER path to privacy_scan.py used to redact sensitive file paths
#   SECRET_SCAN_RULES         optional public rules file for path redaction
#   SECRET_SCAN_NO_PRIVATE    when "1", pass --no-private during path redaction
#
# Exit status: 0 clean, 2 usage error, 3 betterleaks missing, anything else: findings or a
# betterleaks failure. Secret values are never printed (--redact); a finding is one line,
# "rule path:line commit", with sensitive paths redacted when the real privacy scanner is present.
# Validation is off (it would send candidates to the network) and the repository's own
# Betterleaks config is not loaded (--unsafe-auto-load-config is not used).
set -eu

usage() {
  echo "usage: sh tools/secret_scan.sh staged | unstaged | message FILE | history | rev OBJECT | range SPEC | files FILE... | ignore-check --index|OBJECT" >&2
  exit 2
}

[ "$#" -ge 1 ] || usage
mode=$1
case "$mode" in
  staged | unstaged | history) [ "$#" -eq 1 ] || usage ;;
  message) [ "$#" -eq 2 ] && [ -r "$2" ] || usage ;;
  rev | range | ignore-check) [ "$#" -eq 2 ] && [ -n "$2" ] || usage ;;
  files) [ "$#" -ge 2 ] || usage ;;
  *) usage ;;
esac

if ! command -v betterleaks >/dev/null 2>&1; then
  echo "secret_scan: betterleaks is not on PATH, so the secret scan cannot run (a guard that skips itself is no guard)." >&2
  echo "secret_scan: install it with 'brew install betterleaks', or from https://github.com/betterleaks/betterleaks/releases" >&2
  exit 3
fi

here=$(cd "$(dirname "$0")" && pwd)
template="$here/secret_scan.tmpl"
redact_scanner=${SECRET_SCAN_REDACT_SCANNER:-"$here/privacy_scan.py"}

g() {
  git --no-replace-objects "$@"
}

# Scratch space for content streams, and (with an explicit ignore path) the isolated source.
work=$(mktemp -d "${TMPDIR:-/tmp}/secret-scan.XXXXXX")
trap 'rm -rf "$work"' EXIT
trap 'exit 130' INT TERM HUP

ignore_path=${SECRET_SCAN_IGNORE_PATH:-}
src=.
iso=
if [ -n "$ignore_path" ]; then
  case "$ignore_path" in
    /*) ;;
    *) ignore_path="$(pwd)/$ignore_path" ;;
  esac
  if [ ! -e "$ignore_path" ]; then
    echo "secret_scan: SECRET_SCAN_IGNORE_PATH does not exist: $ignore_path" >&2
    exit 2
  fi
  if [ "$mode" = unstaged ]; then
    echo "secret_scan: the unstaged mode reads the working tree, where a .betterleaksignore would apply next to SECRET_SCAN_IGNORE_PATH; use 'files' instead" >&2
    exit 2
  fi
  case "$mode" in
    staged | history | rev | range)
      # Betterleaks reads .betterleaksignore and .gitleaksignore from the root of its source and,
      # for stdin, from the current directory, even when -i names another file (checked with
      # 1.10.1). An empty directory whose .git file points at this repository gives it the same
      # history with nothing else to read.
      iso="$work/src"
      mkdir "$iso"
      gitdir=$(g rev-parse --absolute-git-dir)
      printf 'gitdir: %s\n' "$gitdir" >"$iso/.git"
      src=$iso
      ;;
    message | files)
      iso="$work/src"
      mkdir "$iso"
      ;;
  esac
fi

redact_output() {
  if [ -f "$redact_scanner" ] && grep -q -- '--redact-stream' "$redact_scanner" 2>/dev/null; then
    set -- -I -B "$redact_scanner" --redact-stream
    if [ -n "${SECRET_SCAN_RULES:-}" ]; then
      set -- "$@" --rules "$SECRET_SCAN_RULES"
    fi
    if [ "${SECRET_SCAN_NO_PRIVATE:-0}" = "1" ]; then
      set -- "$@" --no-private
    fi
    if redacted=$(python3 "$@"); then
      printf '%s\n' "$redacted"
    else
      echo "<redacted: path redaction failed; inspect locally>"
    fi
  else
    cat
  fi
}

# bl SUBCOMMAND [ARGS...]: one Betterleaks run with the shared flags; stdin is passed through.
# With an explicit ignore path, git and stdin runs start in the isolated directory (a dir run
# names a single file as its source, so no ignore file is read from beside it).
bl() {
  sub=$1
  if [ -n "$ignore_path" ]; then
    set -- "$@" -i "$ignore_path"
  fi
  if [ "${SECRET_SCAN_IGNORE_ALLOW:-0}" = "1" ]; then
    set -- "$@" --ignore-gitleaks-allow
  fi
  set -- "$@" --redact --no-banner --no-color --log-level warn \
    --report-format template --report-template "$template" --report-path -
  if [ -n "$iso" ] && [ "$sub" != dir ]; then
    (
      cd "$iso"
      unset GIT_DIR GIT_WORK_TREE
      exec betterleaks "$@"
    )
  else
    betterleaks "$@"
  fi
}

# scan LABEL SUBCOMMAND [ARGS...]
scan() {
  label=$1
  shift
  rc=0
  out=$(bl "$@") || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "secret_scan: $label: betterleaks exited $rc" >&2
    if [ -n "$out" ]; then
      printf '%s\n' "$out" | redact_output | sed 's/^/  /' >&2
    fi
    echo "secret_scan: values are redacted. For a false positive see 'Second scan: Betterleaks' in PRIVACY.md." >&2
    return 1
  fi
}

content="$work/content"
commits="$work/commits"
: >"$content"
: >"$commits"

# peel OID: append every tag object above OID to $content, then sort out what the chain ends in:
# a commit id goes to $commits, a tree's blobs and a blob's bytes go to $content. Nothing is
# passed as clean without being read; an unreadable object is a usage error (exit 2).
peel() {
  oid=$1
  depth=0
  while :; do
    type=$(g cat-file -t "$oid" 2>/dev/null) || {
      echo "secret_scan: cannot read object $oid" >&2
      exit 2
    }
    case "$type" in
      tag)
        g cat-file tag "$oid" >"$work/tag"
        cat "$work/tag" >>"$content"
        printf '\n' >>"$content"
        oid=$(sed -n '1s/^object //p' "$work/tag")
        depth=$((depth + 1))
        if [ -z "$oid" ] || [ "$depth" -gt 64 ]; then
          echo "secret_scan: malformed or too deeply nested tag object" >&2
          exit 2
        fi
        ;;
      commit)
        printf '%s\n' "$oid" >>"$commits"
        return 0
        ;;
      tree)
        g ls-tree -r "$oid" >"$work/tree"
        awk '$2 == "blob" { print $3 }' "$work/tree" >"$work/blobs"
        if [ -s "$work/blobs" ]; then
          g cat-file --batch <"$work/blobs" >>"$content"
        fi
        return 0
        ;;
      blob)
        g cat-file blob "$oid" >>"$content"
        printf '\n' >>"$content"
        return 0
        ;;
      *)
        echo "secret_scan: unsupported object type '$type' for $oid" >&2
        exit 2
        ;;
    esac
  done
}

case "$mode" in
  ignore-check)
    top=$(g rev-parse --show-toplevel)
    if [ "$2" = --index ]; then
      label="the index"
    else
      obj=$(g rev-parse --verify --quiet --end-of-options "$2^{object}") || {
        echo "secret_scan: not a git object: $2" >&2
        exit 2
      }
      label="the scanned object $(printf '%s' "$obj" | cut -c1-12)"
      # A blob (or a tag of one) has no tree, so no ignore file comes with it.
      tree=$(g rev-parse --verify --quiet "$obj^{tree}") || tree=
    fi
    rc_all=0
    for name in .betterleaksignore .gitleaksignore; do
      path="$top/$name"
      have=
      if [ -e "$path" ]; then
        # hash-object reads through a symlink, as Betterleaks does; a directory is unreadable.
        have=$(g hash-object --no-filters -- "$path") || {
          echo "secret_scan: cannot read $name in the working tree" >&2
          exit 2
        }
      fi
      if [ "$2" = --index ]; then
        want=$(g rev-parse --verify --quiet ":0:$name") || want=
      elif [ -n "$tree" ]; then
        want=$(g rev-parse --verify --quiet "$tree:$name") || want=
      else
        want=
      fi
      if [ "$have" != "$want" ]; then
        if [ -z "$want" ]; then
          what="exists in the working tree but not in $label"
        elif [ -z "$have" ]; then
          what="is in $label but missing from the working tree"
        else
          what="in the working tree differs from the version in $label"
        fi
        echo "secret_scan: $name $what. Betterleaks would apply the working-tree copy, not the exemptions the scanned content carries. Commit it, restore it, or move it away, then retry." >&2
        rc_all=1
      fi
    done
    exit "$rc_all"
    ;;
  staged)
    scan "staged changes" git --pre-commit --staged "$src"
    ;;
  unstaged)
    scan "unstaged changes" git --pre-commit .
    ;;
  message)
    scan "commit message" stdin <"$2"
    ;;
  history)
    scan "history" git --log-opts="--full-history --all --diff-merges=first-parent" "$src"
    g for-each-ref --format='%(objecttype) %(objectname)' >"$work/refs"
    if [ -s "$work/refs" ]; then
      # Refs to commits are covered by the diff walk above; every other ref is peeled.
      awk '$1 != "commit" { print $2 }' "$work/refs" >"$work/others"
      while read -r oid; do
        peel "$oid" </dev/null
      done <"$work/others"
      g log --all --format='%B' >>"$content"
      scan "commit messages, tag objects, and trees or blobs refs point at" stdin <"$content"
    fi
    ;;
  rev)
    obj=$(g rev-parse --verify --quiet --end-of-options "$2^{object}") || {
      echo "secret_scan: not a git object: $2" >&2
      exit 2
    }
    peel "$obj"
    if [ -s "$commits" ]; then
      commit=$(cat "$commits")
      scan "candidate history" git --log-opts="--diff-merges=first-parent $commit" "$src"
      g log "$commit" --format='%B' >>"$content"
    fi
    if [ -s "$content" ]; then
      scan "candidate messages, tag objects, and tree or blob content" stdin <"$content"
    fi
    ;;
  range)
    spec=$2
    count=$(g rev-list --count "$spec")
    if [ "$count" -gt 0 ]; then
      scan "branch commit range" git --log-opts="--diff-merges=first-parent $spec" "$src"
      g log "$spec" --format='%B' >"$content"
      scan "branch commit messages" stdin <"$content"
    fi
    ;;
  files)
    shift
    rc_all=0
    for target in "$@"; do
      if [ -L "$target" ]; then
        link_text=$(readlink "$target")
        printf '%s\n' "$link_text" | scan "symlink target" stdin || rc_all=1
      elif [ -f "$target" ]; then
        scan "working-tree file" dir "$target" || rc_all=1
      else
        echo "secret_scan: unreadable or missing file: $target" >&2
        exit 2
      fi
    done
    exit "$rc_all"
    ;;
esac
