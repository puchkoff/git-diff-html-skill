#!/usr/bin/env python3
"""Render `git diff` as a self-contained HTML page and open it.

Standalone — no MCP server. Captures a unified diff, builds an HTML page that
renders it client-side with diff2html (loaded from CDN), injects a light-blue
worktree banner and sticky per-file headers, writes the page, and opens it in
Safari on macOS. Defaults to an inline (unified, GitHub-style) view;
--side-by-side switches to the two-pane view.

Usage:
    render_git_diff.py [git diff args...]   # default: HEAD, inline view
    render_git_diff.py main..HEAD -- apps/frontend
    render_git_diff.py --staged
    render_git_diff.py --side-by-side HEAD   # two-pane view instead of inline
    render_git_diff.py --no-open HEAD        # write the file, don't open it

Runs plain `git` directly, so it is not intercepted by the rtk Bash hook.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path.home() / '.local' / 'share' / 'git-diff-html' / 'diff.html'
MAX_FULL_FILE_BYTES = 2_000_000  # skip embedding huge files; the diff still renders

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>git diff{title_suffix}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css" />
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/github.min.css" />
<script src="https://cdn.jsdelivr.net/npm/diff2html/bundles/js/diff2html-ui.min.js"></script>
<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js"></script>
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
  /* Full-file viewer: button per file header + modal popup. */
  .gdh-viewbtn {{
    margin-left: 10px; padding: 1px 8px; font-size: 11px; line-height: 1.6;
    border: 1px solid #cdd3db; border-radius: 5px; background: #fff; color: #2b8def;
    cursor: pointer; vertical-align: 1px;
  }}
  .gdh-viewbtn:hover {{ background: #eef2ff; }}
  #gdh-modal {{
    position: fixed; inset: 0; z-index: 10000; background: rgba(15, 23, 42, .45);
    display: flex; align-items: center; justify-content: center;
  }}
  #gdh-modal[hidden] {{ display: none; }}
  #gdh-modal-box {{
    width: min(1100px, 94vw); height: 90vh; background: #fff; border-radius: 10px;
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 12px 40px rgba(0, 0, 0, .25);
  }}
  #gdh-modal-head {{
    display: flex; align-items: center; gap: 10px; padding: 8px 12px;
    border-bottom: 1px solid #e3e6eb; background: #f7f8fa;
  }}
  #gdh-modal-path {{
    flex: 1; font: 600 12.5px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
    color: #1f2430; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  #gdh-modal-head button {{
    padding: 2px 9px; font-size: 11px; border: 1px solid #cdd3db; border-radius: 5px;
    background: #fff; color: #2b8def; cursor: pointer;
  }}
  #gdh-modal-head button:hover {{ background: #eef2ff; }}
  #gdh-modal-body {{ flex: 1; overflow: auto; }}
  /* Per-line table so changed-line backgrounds span the full scroll width. */
  .gdh-code {{ display: table; min-width: 100%; border-collapse: collapse;
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .gdh-line {{ display: table-row; }}
  .gdh-line.gdh-add {{ background: #e6ffec; }}
  .gdh-line.gdh-add .gdh-ln {{ background: #ccffd8; }}
  .gdh-line.gdh-del .gdh-ln, .gdh-line.gdh-del .gdh-lc {{
    box-shadow: inset 0 2px 0 #f4a8a8;       /* red strip = lines removed above this one */
  }}
  .gdh-ln {{
    display: table-cell; position: sticky; left: 0; min-width: 3em;
    padding: 0 8px 0 14px; text-align: right; color: #9aa3af;
    user-select: none; background: #fafbfc; border-right: 1px solid #eceff3;
  }}
  .gdh-lc {{ display: table-cell; white-space: pre; width: 100%; padding: 0 16px 0 12px; }}
</style>
</head>
<body class="gdh-nav-hidden">
<div id="wt-banner">{banner}</div>
<button id="gdh-toggle" title="Show / hide file tree">&#9776;</button>
<nav id="gdh-nav"><div class="gdh-nav-title">Files</div><ul id="gdh-nav-list"></ul></nav>
<div id="diff"></div>
<div id="gdh-modal" hidden>
  <div id="gdh-modal-box">
    <div id="gdh-modal-head">
      <span id="gdh-modal-path"></span>
      <button id="gdh-modal-newtab" title="Open this file in a new tab">Open in new tab ⧉</button>
      <button id="gdh-modal-close" title="Close (Esc)">✕</button>
    </div>
    <div id="gdh-modal-body"></div>
  </div>
</div>
<script>
  const diffString = JSON.parse({diff_json});
  const fullFiles = JSON.parse({files_json});
  const changedLines = JSON.parse({changed_json});
  const ui = new Diff2HtmlUI(document.getElementById('diff'), diffString, {{
    drawFileList: true,
    fileListToggle: true,
    fileListStartVisible: true,
    matching: 'lines',
    outputFormat: '{output_format}',
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

  // Full-file viewer: a "Full file" button on each file header opens the whole
  // file (embedded at render time) in a highlight.js popup; ⌘/Ctrl-click or the
  // modal's "Open in new tab" renders it as a standalone blob page instead.
  (function fullFileViewer() {{
    if (typeof hljs === 'undefined') return;   // CDN blocked → diff still works
    const LANG = {{
      tsx: 'typescript', ts: 'typescript', jsx: 'javascript', mjs: 'javascript',
      cjs: 'javascript', py: 'python', rs: 'rust', kt: 'kotlin', sh: 'bash',
      zsh: 'bash', yml: 'yaml', md: 'markdown'
    }};
    function esc(s) {{
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }}
    // Split highlighted HTML into lines, re-balancing <span> tags that hljs
    // lets straddle newlines (multi-line strings/comments).
    function splitHighlighted(html) {{
      const out = [];
      const open = [];
      html.split('\\n').forEach(function (line) {{
        const prefix = open.join('');
        const re = /<span[^>]*>|<\\/span>/g;
        let m;
        while ((m = re.exec(line))) {{
          if (m[0] === '</span>') open.pop(); else open.push(m[0]);
        }}
        out.push(prefix + line + '</span>'.repeat(open.length));
      }});
      return out;
    }}
    function codeBlock(path, content) {{
      const ext = (path.split('.').pop() || '').toLowerCase();
      const lang = LANG[ext] || ext;
      let value;
      try {{
        value = hljs.getLanguage(lang)
          ? hljs.highlight(content, {{ language: lang }}).value
          : hljs.highlightAuto(content).value;
      }} catch (err) {{ value = esc(content); }}
      const lines = splitHighlighted(value);
      if (content.endsWith('\\n')) lines.pop();
      const marks = changedLines[path] || {{}};
      const added = new Set(marks.added || []);
      const deleted = new Set(marks.deleted || []);
      let rows = '';
      for (let i = 0; i < lines.length; i++) {{
        const n = i + 1;
        let cls = 'gdh-line';
        if (added.has(n)) cls += ' gdh-add';
        if (deleted.has(n)) cls += ' gdh-del';
        rows += '<div class="' + cls + '"><span class="gdh-ln">' + n +
          '</span><span class="gdh-lc">' + (lines[i] || '\\u200b') + '</span></div>';
      }}
      return '<div class="gdh-code">' + rows + '</div>';
    }}

    const modal = document.getElementById('gdh-modal');
    const modalBody = document.getElementById('gdh-modal-body');
    const modalPath = document.getElementById('gdh-modal-path');
    let currentPath = null;
    function openModal(path) {{
      currentPath = path;
      modalPath.textContent = path;
      modalBody.innerHTML = codeBlock(path, fullFiles[path]);
      modal.hidden = false;
      modalBody.scrollTop = 0;
    }}
    function closeModal() {{
      modal.hidden = true;
      modalBody.innerHTML = '';
      currentPath = null;
    }}
    // Duplicate of the page's .gdh-code styles — the blob tab is a fresh document.
    const TAB_CSS =
      'body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}' +
      '.gdh-filehead{{position:sticky;top:0;padding:8px 14px;background:#f7f8fa;' +
      'border-bottom:1px solid #e3e6eb;font:600 12.5px/1.4 ui-monospace,Menlo,monospace;color:#1f2430}}' +
      '.gdh-code{{display:table;min-width:100%;border-collapse:collapse;' +
      'font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}' +
      '.gdh-line{{display:table-row}}' +
      '.gdh-line.gdh-add{{background:#e6ffec}}' +
      '.gdh-line.gdh-add .gdh-ln{{background:#ccffd8}}' +
      '.gdh-line.gdh-del .gdh-ln,.gdh-line.gdh-del .gdh-lc{{box-shadow:inset 0 2px 0 #f4a8a8}}' +
      '.gdh-ln{{display:table-cell;position:sticky;left:0;min-width:3em;' +
      'padding:0 8px 0 14px;text-align:right;color:#9aa3af;user-select:none;' +
      'background:#fafbfc;border-right:1px solid #eceff3}}' +
      '.gdh-lc{{display:table-cell;white-space:pre;width:100%;padding:0 16px 0 12px}}';
    function openTab(path) {{
      const doc = '<!doctype html><html><head><meta charset="utf-8"><title>' + esc(path) +
        '</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/github.min.css">' +
        '<style>' + TAB_CSS + '</style></head><body><div class="gdh-filehead">' + esc(path) +
        '</div>' + codeBlock(path, fullFiles[path]) + '</body></html>';
      const url = URL.createObjectURL(new Blob([doc], {{ type: 'text/html' }}));
      window.open(url, '_blank');
    }}

    modal.addEventListener('click', function (e) {{ if (e.target === modal) closeModal(); }});
    document.getElementById('gdh-modal-close').addEventListener('click', closeModal);
    document.getElementById('gdh-modal-newtab').addEventListener('click', function () {{
      if (currentPath) {{ const p = currentPath; closeModal(); openTab(p); }}
    }});
    document.addEventListener('keydown', function (e) {{
      if (e.key === 'Escape' && !modal.hidden) closeModal();
    }});

    document.querySelectorAll('#diff .d2h-file-wrapper').forEach(function (w) {{
      const nameEl = w.querySelector('.d2h-file-name');
      if (!nameEl) return;
      const path = nameEl.textContent.trim();
      if (!(path in fullFiles)) return;   // binary, huge, or rename-display path
      const btn = document.createElement('button');
      btn.className = 'gdh-viewbtn';
      btn.textContent = 'Full file';
      btn.title = 'View whole file — click: popup, ⌘-click: new tab';
      btn.addEventListener('click', function (e) {{
        if (e.metaKey || e.ctrlKey) openTab(path); else openModal(path);
      }});
      const header = w.querySelector('.d2h-file-header');
      const nameWrap = header && header.querySelector('.d2h-file-name-wrapper');
      (nameWrap || header || w).appendChild(btn);
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


def repo_root() -> str:
    try:
        return subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return ''


def worktree_name(root: str) -> str:
    if not root:
        return ''
    marker = '/.claude/worktrees/'
    if marker in root:
        return root.split(marker, 1)[1].split('/', 1)[0]
    return Path(root).name


def new_side_paths(diff: str) -> list[str]:
    """New-side paths from `diff --git a/<old> b/<new>` lines (quoted paths skipped)."""
    paths = []
    for line in diff.splitlines():
        if not line.startswith('diff --git '):
            continue
        rest = line[len('diff --git ') :]
        idx = rest.rfind(' b/')
        if idx != -1:
            paths.append(rest[idx + 3 :])
    return paths


HUNK_RE = re.compile(r'@@ -\d+(?:,\d+)? \+(\d+)')


def changed_lines(diff: str) -> dict[str, dict[str, list[int]]]:
    """Per new-side path: 'added' = line numbers of + lines, 'deleted' = the
    line right after a removal (so pure deletions stay visible)."""
    out: dict[str, dict[str, list[int]]] = {}
    cur: dict[str, list[int]] | None = None
    in_hunk = False
    new_ln = 0
    for line in diff.splitlines():
        if line.startswith('diff --git '):
            rest = line[len('diff --git ') :]
            idx = rest.rfind(' b/')
            cur = out.setdefault(rest[idx + 3 :], {'added': [], 'deleted': []}) if idx != -1 else None
            in_hunk = False
        elif line.startswith('@@') and cur is not None:
            m = HUNK_RE.match(line)
            if m:
                new_ln = int(m.group(1))
                in_hunk = True
        elif in_hunk and cur is not None:
            if line.startswith('+'):
                cur['added'].append(new_ln)
                new_ln += 1
            elif line.startswith('-'):
                if not cur['deleted'] or cur['deleted'][-1] != new_ln:
                    cur['deleted'].append(new_ln)
            elif not line.startswith('\\'):  # context; '\ No newline…' counts nothing
                new_ln += 1
    return out


def collect_full_files(paths: list[str], root: str) -> dict[str, str]:
    """Full text per path for the in-page viewer: worktree first, HEAD for deleted files."""
    out: dict[str, str] = {}
    for path in dict.fromkeys(paths):
        text = _read_worktree(Path(root, path) if root else Path(path))
        if text is None:
            text = _read_head(path)
        if text is not None:
            out[path] = text
    return out


def _read_worktree(file: Path) -> str | None:
    try:
        if not file.is_file() or file.stat().st_size > MAX_FULL_FILE_BYTES:
            return None
        return file.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def _read_head(path: str) -> str | None:
    result = subprocess.run(['git', 'show', f'HEAD:{path}'], capture_output=True, check=False)
    if result.returncode != 0 or len(result.stdout) > MAX_FULL_FILE_BYTES:
        return None
    try:
        return result.stdout.decode('utf-8')
    except UnicodeDecodeError:
        return None


def main() -> int:
    args = sys.argv[1:]
    open_it = True
    if '--no-open' in args:
        open_it = False
        args = [a for a in args if a != '--no-open']
    # Inline (unified, GitHub-style) is the default; --side-by-side opts into
    # the two-pane view. Accept --inline too as an explicit no-op alias.
    output_format = 'line-by-line'
    if '--side-by-side' in args:
        output_format = 'side-by-side'
    args = [a for a in args if a not in ('--side-by-side', '--inline')]
    if not args:
        args = ['HEAD']

    diff = capture_diff(args)
    if not diff.strip():
        print('No changes to diff.')
        return 0

    root = repo_root()
    name = worktree_name(root)
    full_files = collect_full_files(new_side_paths(diff), root)
    # JSON-encode twice: once to embed safely in the page, once so JSON.parse in
    # the browser rebuilds the exact value regardless of backticks/newlines.
    # Escape <, >, & to their \uXXXX forms so a file (or diff) containing the
    # literal "</script>" can't close this inline <script> early and inject —
    # JSON.parse still decodes the escapes back to the exact characters.
    def embed(value: object) -> str:
        return (
            json.dumps(json.dumps(value))
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026')
        )

    diff_json = embed(diff)
    files_json = embed(full_files)
    changed_json = embed(changed_lines(diff))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        PAGE.format(
            title_suffix=f' — {name}' if name else '',
            banner=name,
            output_format=output_format,
            diff_json=diff_json,
            files_json=files_json,
            changed_json=changed_json,
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
