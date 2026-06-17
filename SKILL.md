---
name: git-diff-html
version: 1.0.0
description: Render `git diff` as an HTML page (inline/unified view by default, like GitHub) and open it in Safari. Use when the user says "/git-diff-html", "git-diff-html", "/git-diff", "git-diff", "gdh", "show the diff visually", "open diff in browser", "show diff in safari", "diff html", or asks to visualize current changes. Accepts the same args as `git diff` (e.g. `HEAD`, `--staged`, `main..HEAD`, a path), plus `--side-by-side` for the two-pane view.
---

# git-diff-html — Git Diff → HTML → Safari

Run the bundled `render_git_diff.py` (next to this file). It captures the diff, builds a self-contained HTML page with diff2html (CDN), adds a light-blue worktree banner + sticky per-file headers, and opens it in Safari. Defaults to an **inline (unified, GitHub-style)** view; pass `--side-by-side` for the two-pane view. No MCP server needed.

## Args

`$@` — anything valid after `git diff`:
- (no args) → defaults to `HEAD` (staged + unstaged), inline view
- `--staged`/`--cached` → staged only
- `main..HEAD` → branch diff · `HEAD~3 -- apps/frontend` → range scoped to a path
- `--side-by-side` → two-pane view instead of the default inline/unified (`--inline` is an explicit no-op alias)
- `--no-open` → write the file but don't launch Safari

## Run it

Run from inside the repo (or worktree) you want to diff — the script shells out to plain `git` in the current directory, so `cd` to the target tree first.

```bash
python3 ~/.claude/skills/git-diff/render_git_diff.py "$@"
# e.g. inside a worktree:
#   cd .claude/worktrees/<name> && python3 ~/.claude/skills/git-diff/render_git_diff.py origin/main -- apps/backend
```

The script prints the output path + file count, or `No changes to diff.` and exits when the diff is empty. Relay that one line; don't paste the diff.

## What the page does

- **Top file list** — diff2html's own summary of changed files (`drawFileList: true`).
- **Left file tree** — a fixed, full-height sidebar showing the changed files as a collapsible directory tree (single-child dir chains fold onto one row, so long paths stay readable). Click a folder to fold it, click a file to jump; a scrollspy highlights the file currently at the top of the viewport. The `☰` button (top-left) shows/hides the sidebar — the diff column and banner reflow to fill the space.
- **Worktree banner** — fixed, top-center over the diff column, light-blue (`#2b8def`); shows the worktree name (or repo basename outside a worktree).
- **Sticky file headers** — each file's header pins to the top of the window as you scroll; the next file's header pushes it off. The script overrides diff2html's `.d2h-wrapper { overflow-x: auto }` back to `visible`, because that overflow makes the wrapper a scroll container and silently kills `position: sticky`.
- **Full-file viewer** — a `Full file` button in each file header opens the whole file in a syntax-highlighted popup (highlight.js, line numbers, Esc/✕ to close). Changed lines are colored in place: added/modified lines get a green background, and a thin red strip marks where lines were removed. ⌘-click the button — or use the popup's `Open in new tab ⧉` — to open the file as a standalone tab instead. File contents are embedded at render time: worktree version, falling back to `HEAD:<path>` for deleted files; binary, >2 MB, and quoted/rename-display paths are skipped (no button).

## Notes

- Always writes to `~/.local/share/git-diff-html/diff.html`, overwriting each run.
- Read-only: runs `git diff` only — never stages, never commits, never touches the working tree.
- Self-contained: only external dependencies are the diff2html and highlight.js CDN bundles (needs network to render; if highlight.js fails to load, the diff still works — only the full-file buttons are missing).
