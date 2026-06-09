#!/usr/bin/env python3
"""Render `git diff` as a self-contained side-by-side HTML page and open it.

Standalone — no MCP server. Captures a unified diff, builds an HTML page that
renders it client-side with diff2html (loaded from CDN), injects a light-blue
worktree banner and sticky per-file headers, writes the page, and opens it in
Safari on macOS.

Usage:
    render_git_diff.py [git diff args...]   # default: HEAD
    render_git_diff.py main..HEAD -- apps/frontend
    render_git_diff.py --staged
    render_git_diff.py --no-open HEAD        # write the file, don't open it

Runs plain `git` directly, so it is not intercepted by the rtk Bash hook.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

OUT = Path.home() / '.local' / 'share' / 'git-diff-html' / 'diff.html'

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>git diff{title_suffix}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css" />
<script src="https://cdn.jsdelivr.net/npm/diff2html/bundles/js/diff2html-ui.min.js"></script>
<style>
  body {{ margin: 0; background: #fff; }}
  /* diff2html puts overflow-x:auto on .d2h-wrapper, which makes it a scroll
     container and silently kills position:sticky for everything inside it. */
  .d2h-wrapper {{ overflow: visible; }}
  .d2h-file-wrapper {{ overflow: visible; }}
  /* Pin the current file's header to the top while scrolling; the next file's
     header pushes it off as it arrives. top:26px clears the banner. */
  .d2h-file-header {{
    position: sticky;
    top: 26px;
    z-index: 50;
    background: #fff;
    box-shadow: 0 1px 0 rgba(16, 24, 40, .12);
  }}
  #wt-banner {{
    position: fixed; top: 4px; left: 50%; transform: translateX(-50%);
    color: #2b8def; font-weight: bold; font-size: 13px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    z-index: 9999; pointer-events: none;
  }}
</style>
</head>
<body>
<div id="wt-banner">{banner}</div>
<div id="diff"></div>
<script>
  const diffString = JSON.parse({diff_json});
  const ui = new Diff2HtmlUI(document.getElementById('diff'), diffString, {{
    drawFileList: true,
    matching: 'lines',
    outputFormat: 'side-by-side',
    highlight: true,
  }});
  ui.draw();
  ui.highlightCode();
</script>
</body>
</html>
"""


def capture_diff(args: list[str]) -> str:
    result = subprocess.run(
        ['git', '--no-pager', 'diff', *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout:
        sys.stderr.write(result.stderr)
    return result.stdout


def worktree_name() -> str:
    try:
        root = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return ''
    marker = '/.claude/worktrees/'
    if marker in root:
        return root.split(marker, 1)[1].split('/', 1)[0]
    return Path(root).name


def main() -> int:
    args = sys.argv[1:]
    open_it = True
    if '--no-open' in args:
        open_it = False
        args = [a for a in args if a != '--no-open']
    if not args:
        args = ['HEAD']

    diff = capture_diff(args)
    if not diff.strip():
        print('No changes to diff.')
        return 0

    name = worktree_name()
    # JSON-encode twice: once to embed safely in the page, once so JSON.parse in
    # the browser rebuilds the exact string regardless of backticks/newlines.
    diff_json = json.dumps(json.dumps(diff))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        PAGE.format(
            title_suffix=f' — {name}' if name else '',
            banner=name,
            diff_json=diff_json,
        ),
        encoding='utf-8',
    )

    files = diff.count('\ndiff --git ') + diff.startswith('diff --git ')
    print(f'Wrote {OUT} ({files} file(s)).')
    if open_it:
        subprocess.run(['open', '-a', 'Safari', str(OUT)], check=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
