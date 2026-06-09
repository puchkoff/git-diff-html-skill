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
  :root {{ --nav-w: 270px; }}
  body {{ margin: 0; background: #fff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  /* diff2html puts overflow-x:auto on .d2h-wrapper, which makes it a scroll
     container and silently kills position:sticky for everything inside it. */
  .d2h-wrapper {{ overflow: visible; }}
  .d2h-file-wrapper {{ overflow: visible; scroll-margin-top: 34px; }}
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
    position: fixed; top: 4px; left: calc(var(--nav-w) + 50%); transform: translateX(-50%);
    color: #2b8def; font-weight: bold; font-size: 13px;
    z-index: 9999; pointer-events: none;
  }}
  /* Left file-nav (tree). Fixed full height, scrolls on its own. */
  #gdh-nav {{
    position: fixed; top: 0; left: 0; width: var(--nav-w); height: 100vh;
    overflow: auto; box-sizing: border-box; padding: 38px 0 24px;
    background: #f7f8fa; border-right: 1px solid #e3e6eb; z-index: 9000;
    transition: transform .18s ease;
  }}
  #gdh-nav .gdh-nav-title {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
    color: #6b7280; padding: 6px 16px 8px; font-weight: 700;
  }}
  #gdh-nav ul {{ list-style: none; margin: 0; padding: 0; }}
  /* Nested levels indent and draw a vertical guide line down the hierarchy. */
  #gdh-nav ul ul {{ margin-left: 13px; padding-left: 7px; border-left: 1px solid #d8dce2; }}
  .gdh-row {{
    display: block; font-size: 12.5px; line-height: 1.5; padding: 3px 12px 3px 9px;
    color: #1f2430; text-decoration: none; border-left: 3px solid transparent;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer;
  }}
  .gdh-dir {{ color: #4b5563; font-weight: 600; }}
  .gdh-dir::before {{ content: "\\25be "; color: #9aa3af; }}      /* ▾ open  */
  .gdh-dir.collapsed::before {{ content: "\\25b8 "; }}            /* ▸ closed */
  a.gdh-row:hover {{ background: #eef2ff; }}
  a.gdh-row.active {{
    background: #eaf3fd; border-left-color: #2b8def; color: #0b62b6; font-weight: 600;
  }}
  .gdh-collapsed {{ display: none !important; }}
  /* Show/hide toggle — stays put when the nav slides away. */
  #gdh-toggle {{
    position: fixed; top: 6px; left: 8px; z-index: 9500;
    width: 26px; height: 24px; border: 1px solid #cdd3db; border-radius: 6px;
    background: #fff; color: #2b8def; font-size: 14px; line-height: 1; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
  }}
  #gdh-toggle:hover {{ background: #eef2ff; }}
  #diff {{ margin-left: var(--nav-w); transition: margin-left .18s ease; }}
  /* Keep diff2html's top "Files changed" summary clear of the fixed banner. */
  .d2h-file-list-wrapper {{ margin-top: 8px; }}
  body.gdh-nav-hidden #gdh-nav {{ transform: translateX(-100%); }}
  /* Nav gone → content fills the width; indent it clear of the fixed toggle. */
  body.gdh-nav-hidden #diff {{ margin-left: 0; padding-left: 44px; }}
  body.gdh-nav-hidden #wt-banner {{ left: 50%; }}
</style>
</head>
<body class="gdh-nav-hidden">
<div id="wt-banner">{banner}</div>
<button id="gdh-toggle" title="Show / hide file tree">&#9776;</button>
<nav id="gdh-nav"><div class="gdh-nav-title">Files</div><ul id="gdh-nav-list"></ul></nav>
<div id="diff"></div>
<script>
  const diffString = JSON.parse({diff_json});
  const ui = new Diff2HtmlUI(document.getElementById('diff'), diffString, {{
    drawFileList: true,
    fileListToggle: true,
    fileListStartVisible: true,
    matching: 'lines',
    outputFormat: 'side-by-side',
    highlight: true,
  }});
  ui.draw();
  ui.highlightCode();

  // Build the left nav as a collapsible directory tree from the rendered file
  // blocks: click a file to jump, click a folder to fold it, and a scrollspy
  // marks the file currently under the top of the viewport. A tree keeps long
  // paths readable — each level shows only its own segment.
  (function buildNav() {{
    const wrappers = Array.from(document.querySelectorAll('.d2h-file-wrapper'));
    const root = {{ dirs: new Map(), files: [] }};
    wrappers.forEach(function (w, idx) {{
      if (!w.id) w.id = 'gdh-file-' + idx;
      const nameEl = w.querySelector('.d2h-file-name');
      const path = (nameEl ? nameEl.textContent.trim() : 'file ' + (idx + 1));
      const parts = path.split('/');
      let node = root;
      for (let i = 0; i < parts.length - 1; i++) {{
        const seg = parts[i];
        if (!node.dirs.has(seg)) node.dirs.set(seg, {{ dirs: new Map(), files: [] }});
        node = node.dirs.get(seg);
      }}
      node.files.push({{ label: parts[parts.length - 1], wrapper: w }});
    }});

    const list = document.getElementById('gdh-nav-list');
    const linkFor = new Map();

    function render(node, parentUl) {{
      // Collapse single-child directory chains (a/b/c) onto one row.
      Array.from(node.dirs.entries()).forEach(function (entry) {{
        let label = entry[0];
        let child = entry[1];
        while (child.files.length === 0 && child.dirs.size === 1) {{
          const only = Array.from(child.dirs.entries())[0];
          label += '/' + only[0];
          child = only[1];
        }}
        const dirRow = document.createElement('div');
        dirRow.className = 'gdh-row gdh-dir';
        dirRow.textContent = label;
        dirRow.title = label;
        const childUl = document.createElement('ul');
        dirRow.addEventListener('click', function () {{
          dirRow.classList.toggle('collapsed');
          childUl.classList.toggle('gdh-collapsed');
        }});
        const li = document.createElement('li');
        li.appendChild(dirRow);
        li.appendChild(childUl);
        parentUl.appendChild(li);
        render(child, childUl);
      }});
      node.files.forEach(function (f) {{
        const a = document.createElement('a');
        a.className = 'gdh-row';
        a.href = '#' + f.wrapper.id;
        a.textContent = f.label;
        a.title = f.label;
        a.addEventListener('click', function (e) {{
          e.preventDefault();
          f.wrapper.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }});
        const li = document.createElement('li');
        li.appendChild(a);
        parentUl.appendChild(li);
        linkFor.set(f.wrapper, a);
      }});
    }}
    render(root, list);

    const obs = new IntersectionObserver(function (entries) {{
      entries.forEach(function (en) {{
        if (!en.isIntersecting) return;
        list.querySelectorAll('a.active').forEach(function (x) {{ x.classList.remove('active'); }});
        const a = linkFor.get(en.target);
        if (a) {{ a.classList.add('active'); a.scrollIntoView({{ block: 'nearest' }}); }}
      }});
    }}, {{ rootMargin: '-30px 0px -75% 0px', threshold: 0 }});
    wrappers.forEach(function (w) {{ obs.observe(w); }});

    document.getElementById('gdh-toggle').addEventListener('click', function () {{
      document.body.classList.toggle('gdh-nav-hidden');
    }});
  }})();
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
