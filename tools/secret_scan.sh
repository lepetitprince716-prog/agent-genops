#!/bin/sh
# Second secret scan, next to tools/privacy_scan.py: wraps Betterleaks.
#
#   sh tools/secret_scan.sh staged           the index, as the next commit would contain it
#   sh tools/secret_scan.sh unstaged         working-tree diff relative to the index
#   sh tools/secret_scan.sh message FILE     one commit message file
#   sh tools/secret_scan.sh history          every commit diff on any ref, plus all commit
#                                            and tag messages (Betterleaks itself scans diffs only)
#   sh tools/secret_scan.sh rev COMMIT       commits reachable from COMMIT, plus their messages
#   sh tools/secret_scan.sh range BASE..HEAD commits in a range, plus their messages
#   sh tools/secret_scan.sh files FILE...    specific working-tree files (symlinks not followed)
#
# Optional environment controls:
#   SECRET_SCAN_IGNORE_PATH   explicit .betterleaksignore/.gitleaksignore file or directory
#   SECRET_SCAN_IGNORE_ALLOW  when "1", pass --ignore-gitleaks-allow
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
  echo "usage: sh tools/secret_scan.sh staged | unstaged | message FILE | history | rev COMMIT | range SPEC | files FILE..." >&2
  exit 2
}

[ "$#" -ge 1 ] || usage
mode=$1
case "$mode" in
  staged | unstaged | history) [ "$#" -eq 1 ] || usage ;;
  message) [ "$#" -eq 2 ] && [ -r "$2" ] || usage ;;
  rev | range) [ "$#" -eq 2 ] && [ -n "$2" ] || usage ;;
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

# scan LABEL SUBCOMMAND [ARGS...]: stdin, when the subcommand reads it, is passed through.
scan() {
  label=$1
  shift
  rc=0
  if [ -n "${SECRET_SCAN_IGNORE_PATH:-}" ] && [ "${SECRET_SCAN_IGNORE_ALLOW:-0}" = "1" ]; then
    out=$(betterleaks "$@" -i "$SECRET_SCAN_IGNORE_PATH" --ignore-gitleaks-allow \
      --redact --no-banner --no-color --log-level warn \
      --report-format template --report-template "$template" --report-path -) || rc=$?
  elif [ -n "${SECRET_SCAN_IGNORE_PATH:-}" ]; then
    out=$(betterleaks "$@" -i "$SECRET_SCAN_IGNORE_PATH" \
      --redact --no-banner --no-color --log-level warn \
      --report-format template --report-template "$template" --report-path -) || rc=$?
  elif [ "${SECRET_SCAN_IGNORE_ALLOW:-0}" = "1" ]; then
    out=$(betterleaks "$@" --ignore-gitleaks-allow \
      --redact --no-banner --no-color --log-level warn \
      --report-format template --report-template "$template" --report-path -) || rc=$?
  else
    out=$(betterleaks "$@" --redact --no-banner --no-color --log-level warn \
      --report-format template --report-template "$template" --report-path -) || rc=$?
  fi
  if [ "$rc" -ne 0 ]; then
    echo "secret_scan: $label: betterleaks exited $rc" >&2
    if [ -n "$out" ]; then
      printf '%s\n' "$out" | redact_output | sed 's/^/  /' >&2
    fi
    echo "secret_scan: values are redacted. For a false positive see 'Second scan: Betterleaks' in PRIVACY.md." >&2
    return 1
  fi
}

case "$mode" in
  staged)
    scan "staged changes" git --pre-commit --staged .
    ;;
  unstaged)
    scan "unstaged changes" git --pre-commit .
    ;;
  message)
    scan "commit message" stdin <"$2"
    ;;
  history)
    scan "history" git .
    refs=$(git --no-replace-objects for-each-ref --count=1)
    if [ -n "$refs" ]; then
      commits=$(git --no-replace-objects log --all --format='%B')
      tags=$(git --no-replace-objects for-each-ref --format='%(contents)' refs/tags)
      printf '%s\n%s\n' "$commits" "$tags" | scan "commit and tag messages" stdin
    fi
    ;;
  rev)
    rev=$2
    git --no-replace-objects rev-parse --verify --quiet "$rev^{commit}" >/dev/null || {
      echo "secret_scan: invalid commit: $rev" >&2
      exit 2
    }
    scan "candidate history" git --log-opts="$rev" .
    commits=$(git --no-replace-objects log "$rev" --format='%B')
    printf '%s\n' "$commits" | scan "candidate commit messages" stdin
    ;;
  range)
    spec=$2
    count=$(git --no-replace-objects rev-list --count "$spec")
    if [ "$count" -gt 0 ]; then
      scan "branch commit range" git --log-opts="$spec" .
      commits=$(git --no-replace-objects log "$spec" --format='%B')
      printf '%s\n' "$commits" | scan "branch commit messages" stdin
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
