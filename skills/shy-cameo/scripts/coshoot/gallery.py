"""Local gallery page: render project status into WS/gallery.html for the user to look at.

Read-only over every record; the only write is gallery.html. No scripts, no external resources,
no buttons -- choosing a version or accepting a shot still happens in the conversation.
"""
from __future__ import annotations

import os
import tempfile
from html import escape
from pathlib import Path
from urllib.parse import quote

from . import projects
from .cards import CardError

PAGE = 'gallery.html'
STYLE = ('body{font:16px/1.7 system-ui,sans-serif;color:#202d29;background:#f7f5f0;margin:0}'
         'main{max-width:1300px;margin:auto;padding:28px}a{color:#245d45}'
         '.grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}'
         'img{width:100%;height:auto;border-radius:8px}figure{margin:0 0 8px}figcaption{font-size:13px}'
         '.versions{display:flex;gap:6px}.versions figure{flex:1 1 0;min-width:0}'
         '.note{padding:16px;background:#eee8d9}.state{font-weight:600}.pick{color:#245d45}'
         '.empty{background:#e2ded4;border-radius:8px;padding:40px 0;text-align:center;font-size:13px}'
         'h2{border-top:1px solid #cfcfc4;padding-top:20px}'
         '@media(max-width:800px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:18px}}')
FAILED = {'failed', 'rejected', 'cancelled', 'unknown'}


def _state(shot: dict) -> str:
    generation = shot.get('generation')
    if generation == 'pending':
        return '未拍'
    if generation == 'claimed':
        return '进行中'
    if generation == 'generated':
        return '你已接受' if shot.get('delivered') and shot.get('verdict') == 'accepted' else '已生成'
    return '失败'


def _relative(ws: Path, value: str, issues: list) -> str | None:
    try:
        path = projects.local_path(ws, value)
    except CardError as exc:
        issues.append(f'{value}: {exc}')
        return None
    return Path(os.path.relpath(path, ws)).as_posix()


def _url(rel: str) -> str:
    # Percent-encode so a file named like "javascript:..." can never read as a URL scheme.
    return escape(quote(rel))


def _version(ws: Path, version: dict, selected: str | None, issues: list) -> str:
    """selected is None unless the shot has several versions side by side."""
    image = version.get('image_path')
    rel = _relative(ws, image, issues) if image else None
    parts = ['<figure>']
    parts.append(f'<img src="{_url(rel)}" alt="">' if rel else '<div class="empty">无图</div>')
    caption = [escape(version.get('title') or '（无描述）')]
    if version.get('run_id') and version.get('run_id') == selected:
        caption.insert(0, '<span class="pick">选用</span>')
    if rel:
        caption.append(f'原图：{escape(rel)}')
    if version.get('issue'):
        caption.append(escape(str(version['issue'])))
    parts.append('<figcaption>' + '<br>'.join(caption) + '</figcaption></figure>')
    return ''.join(parts)


def _set(ws: Path, series_title: str, report: dict, issues: list) -> str:
    set_id = report.get('set_id', '')
    out = [f'<section><h2>{escape(series_title)} · {escape(set_id)}</h2>']
    shots = report.get('shots') or []
    if not shots:
        out.append('<p class="note">这套记录有问题，暂时无法显示。<br>'
                   + '<br>'.join(escape(str(i)) for i in report.get('issues', [])) + '</p>')
    else:
        if report.get('issues'):
            out.append('<p class="note">' + '<br>'.join(escape(str(i)) for i in report['issues']) + '</p>')
        out.append('<div class="grid">')
        for shot in shots:
            versions = shot.get('versions', [])
            selected = shot.get('selected_run_id') if len(versions) > 1 else None
            body = ''.join(_version(ws, v, selected, issues) for v in versions)
            out.append(f'<div class="cell"><p class="state">第 {shot.get("index")} 张 · {_state(shot)}</p>'
                       f'<div class="versions">{body}</div></div><!-- /cell -->')
        out.append('</div>')
    if set_id and (ws / 'captions' / f'{set_id}.md').is_file():
        rel = _relative(ws, f'captions/{set_id}.md', issues)
        if rel:
            out.append(f'<p><a href="{_url(rel)}">发帖文案草稿</a></p>')
    out.append('</section>')
    return ''.join(out)


def build(workspace: Path, project='project.json') -> dict:
    ws = Path(workspace).resolve()
    status = projects.status(ws, project)
    issues = list(status['issues'])
    sections, images = [], 0
    for series in status['series']:
        for report in series['sets']:
            sections.append(_set(ws, series.get('title', ''), report, issues))
            images += sum(bool(v.get('image_path')) for s in report.get('shots', []) for v in s.get('versions', []))
    html = ('<!doctype html><html lang="zh"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(status["title"])} · 作品页</title><style>{STYLE}</style></head><body><main>'
            f'<h1>{escape(status["title"])}</h1>'
            '<p class="note">这个页面只用来看。想选哪一版、接受或重拍，请回到对话里说。</p>'
            + ''.join(sections) + '</main></body></html>\n')
    # Write a temp file and rename over the page: a symlinked gallery.html is replaced, never followed.
    fd, tmp = tempfile.mkstemp(dir=ws, prefix='.gallery-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(html)
        os.replace(tmp, ws / PAGE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {'status': 'gallery_written', 'path': PAGE, 'sets': len(sections), 'images': images, 'issues': issues}
