---
name: git-diff-html
description: Render `git diff` as a side-by-side HTML page and open it in Safari. Use when the user says "/git-diff-html", "git-diff-html", "gdh", "git diff html safari", "show diff in safari", "diff html". Accepts the same args as `git diff` (e.g. `HEAD`, `--staged`, `main..HEAD`, a path).
---

# git-diff-html — Git Diff → HTML → Safari

Run the bundled `render_git_diff.py` (next to this file). It captures the diff, builds a self-contained side-by-side HTML page with diff2html (CDN), adds a light-blue worktree banner + sticky per-file headers, and opens it in Safari. No MCP server needed.

## Args

`$@` — anything valid after `git diff`:
- (no args) → defaults to `HEAD` (staged + unstaged)
- `--staged`/`--cached` → staged only
- `main..HEAD` → branch diff · `HEAD~3 -- apps/frontend` → range scoped to a path
- `--no-open` → write the file but don't launch Safari

## Run it

Run from inside the repo (or worktree) you want to diff — the script shells out to plain `git` in the current directory, so `cd` to the target tree first.

```bash
python3 ~/.claude/skills/git-diff-html/render_git_diff.py "$@"
# e.g. inside a worktree:
#   cd .claude/worktrees/<name> && python3 ~/.claude/skills/git-diff-html/render_git_diff.py origin/main -- apps/backend
```

The script prints the output path + file count, or `No changes to diff.` and exits when the diff is empty. Relay that one line; don't paste the diff.

## What the page does

- **Worktree banner** — fixed, top-center, light-blue (`#2b8def`); shows the worktree name (or repo basename outside a worktree).
- **Sticky file headers** — each file's header pins to the top of the window as you scroll; the next file's header pushes it off. The script overrides diff2html's `.d2h-wrapper { overflow-x: auto }` back to `visible`, because that overflow makes the wrapper a scroll container and silently kills `position: sticky`.

## Notes

- Always writes to `~/.local/share/git-diff-html/diff.html`, overwriting each run.
- Read-only: runs `git diff` only — never stages, never commits, never touches the working tree.
- Self-contained: only external dependency is the diff2html CDN bundle (needs network to render).
