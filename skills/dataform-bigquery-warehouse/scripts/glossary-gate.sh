#!/usr/bin/env bash
# Claude Code PreToolUse hook (tool: Bash): the glossary gate.
#
# Blocks a `git commit` in a Dataform repository that has docs/glossary.md when the commit changes
# files under definitions/ or includes/ but neither includes docs/glossary.md nor carries the
# trailer "Glossary: unchanged". Exit 2 blocks the tool call, and stderr is the message Claude reads.
# Anything else exits 0 silently, which leaves Claude Code's normal permission flow untouched.
#
# Needs only bash, grep, sed and git (no jq): the raw hook JSON is searched as text.

set -u

input=$(cat)

has() { printf '%s' "$input" | grep -qE "$1"; }

# 1. Only git commit commands, including compound ones like `git add -A && git commit -m ...`.
has '(^|[^[:alnum:]_-])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([^[:alnum:]_-]|$)' || exit 0

# 2. Find the repository: `git -C <dir>`, else `cd <dir> &&`, else the hook's cwd.
cwd=$(printf '%s' "$input" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)
dir=${cwd:-${CLAUDE_PROJECT_DIR:-$PWD}}
target=$(printf '%s' "$input" | sed -n 's/.*git[[:space:]]\{1,\}-C[[:space:]]\{1,\}\([^[:space:]"\\]\{1,\}\).*/\1/p' | head -n 1)
if [ -z "$target" ]; then
  target=$(printf '%s' "$input" | sed -n 's/.*cd[[:space:]]\{1,\}\([^[:space:]"\\&;]\{1,\}\)[[:space:]]*&&.*/\1/p' | head -n 1)
fi
if [ -n "$target" ]; then
  case "$target" in
    /*) dir=$target ;;
    *) dir="$dir/$target" ;;
  esac
fi

top=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null) || exit 0

# 3. Only Dataform repositories that keep a glossary.
[ -f "$top/workflow_settings.yaml" ] || [ -f "$top/dataform.json" ] || exit 0
[ -f "$top/docs/glossary.md" ] || exit 0

# 4. What the commit will contain. A `git add` in the same command hasn't run yet, so then look at
#    the whole working tree; `commit -a` takes every tracked change; otherwise take the index.
if has '(^|[^[:alnum:]_-])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+add([^[:alnum:]_-]|$)'; then
  changed=$( { git -C "$top" diff HEAD --name-only; git -C "$top" diff --cached --name-only; git -C "$top" ls-files --others --exclude-standard; } 2>/dev/null )
elif has 'commit.*[[:space:]](-[[:alpha:]]*a[[:alpha:]]*|--all)([[:space:]]|\\|"|$)'; then
  changed=$( { git -C "$top" diff HEAD --name-only; git -C "$top" diff --cached --name-only; } 2>/dev/null )
else
  changed=$(git -C "$top" diff --cached --name-only 2>/dev/null)
fi

model_changes=$(printf '%s\n' "$changed" | grep -E '^(definitions|includes)/' | sort -u)
[ -n "$model_changes" ] || exit 0

# 5. The glossary is part of the commit, or the author confirmed that nothing belongs in it.
printf '%s\n' "$changed" | grep -qx 'docs/glossary.md' && exit 0
printf '%s' "$input" | grep -qiE 'glossary:[[:space:]]*unchanged' && exit 0

count=$(printf '%s\n' "$model_changes" | wc -l | tr -d ' ')
{
  echo "Glossary check: this commit changes $count file(s) under definitions/ or includes/, but docs/glossary.md is not part of it:"
  printf '%s\n' "$model_changes" | head -n 15 | sed 's/^/  - /'
  if [ "$count" -gt 15 ]; then echo "  ... and $((count - 15)) more"; fi
  echo
  echo "Before committing, review the diff and update docs/glossary.md: new, renamed or removed models,"
  echo "columns, business terms, codes, measures, sources, business units, targets, cut-offs and misleading"
  echo "names (the dataform-bigquery-warehouse skill's references/glossary.md says which change goes in which"
  echo "section). Then stage the glossary and commit again."
  echo "If nothing in this change belongs in the glossary (a pure refactor, formatting or comments), commit"
  echo "again with the trailer 'Glossary: unchanged' in the commit message."
} >&2
exit 2
