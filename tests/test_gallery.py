"""Local gallery page: read-only render of project status into WS/gallery.html."""
import json
import re
import subprocess
import sys

from coshoot import gallery, projects
from test_projects import CLI, project, record, save  # noqa: F401  (project is a fixture)


def cells(html):
    return re.findall(r'<div class="cell">(.*?)</div><!-- /cell -->', html, re.S)


def test_delivered_set_with_retake_and_accepted_shot(project, png_factory):
    ws, doc, cards = project
    card = cards['studio']
    card['shots'][0]['title'] = '后台对镜'
    save(ws / 'cards/studio.json', card)
    for index in range(1, 6):
        record(ws, card, index, png_factory, accepted=(index == 2))
    new = record(ws, card, 4, png_factory, retake=True)
    entry = doc['series'][0]['sets'][0]
    entry['shots'] = [{'index': 4, 'selected_run_id': new,
                       'candidates': [{'run_id': new, 'scene_card': f'cards/{new}.json'}]}]
    save(ws / 'project.json', doc)
    result = gallery.build(ws)
    assert result['status'] == 'gallery_written' and result['path'] == 'gallery.html'
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    studio = html.split('studio', 1)[1].split('<section', 1)[0]
    got = cells(studio)
    assert len(got) == 5
    assert '你已接受' in got[1]
    assert all('已生成' in got[i] for i in (0, 2, 3, 4))
    assert got[3].count('<img ') == 2 and got[3].count('选用') == 1
    assert '<div class="versions">' in got[3]  # retakes sit side by side
    assert '选用' not in got[0]  # single version: nothing to choose between
    assert '后台对镜' in got[0]
    assert 'outputs/' in got[0] and str(ws) not in html  # relative paths only


def test_failed_cover_marks_all_five_failed(project, png_factory):
    ws, _, cards = project
    record(ws, cards['training'], 1, png_factory, outcome='failed')
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    training = html.split('training', 1)[1].split('<section', 1)[0]
    got = cells(training)
    assert len(got) == 5 and all('失败' in c for c in got)


def test_pending_and_claimed_states(project, png_factory):
    ws, _, cards = project
    record(ws, cards['daily'], 1, png_factory, outcome='claimed')
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    daily = cells(html.split('daily', 1)[1].split('<section', 1)[0])
    assert '进行中' in daily[0] and all('未拍' in c for c in daily[1:])


def test_broken_set_shows_issue_without_cells(project):
    ws, _, _ = project
    (ws / 'cards/daily.json').unlink()
    result = gallery.build(ws)
    assert result['issues']
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    daily = html.split('daily', 1)[1].split('<section', 1)[0]
    assert '这套记录有问题' in daily and not cells(daily)


def test_broken_retake_version_renders_issue(project, png_factory):
    ws, doc, cards = project
    for index in range(1, 6):
        record(ws, cards['studio'], index, png_factory)
    doc['series'][0]['sets'][0]['shots'] = [
        {'index': 2, 'candidates': [{'run_id': '20261017-999999-ffffff', 'scene_card': 'cards/missing.json'}]}]
    save(ws / 'project.json', doc)
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    second = cells(html.split('studio', 1)[1].split('<section', 1)[0])[1]
    assert '无图' in second and '（无描述）' in second


def test_text_is_escaped_and_page_is_offline(project, png_factory):
    ws, doc, cards = project
    card = cards['studio']
    card['shots'][0]['title'] = '<script>alert(1)</script>'
    save(ws / 'cards/studio.json', card)
    doc['series'][0]['title'] = '<b>x</b>'
    save(ws / 'project.json', doc)
    record(ws, card, 1, png_factory)
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    assert '<script' not in html and '&lt;script&gt;' in html and '<b>x' not in html
    assert 'http://' not in html and 'https://' not in html


def test_caption_link_only_when_draft_exists(project):
    ws, _, _ = project
    gallery.build(ws)
    assert '发帖文案草稿' not in (ws / 'gallery.html').read_text(encoding='utf-8')
    (ws / 'captions').mkdir()
    (ws / 'captions/studio.md').write_text('标题', encoding='utf-8')
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    assert 'href="captions/studio.md"' in html and '发帖文案草稿' in html


def test_gallery_does_not_touch_records(project, png_factory):
    ws, _, cards = project
    record(ws, cards['studio'], 1, png_factory)
    before = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file()}
    gallery.build(ws)
    after = {p: p.read_bytes() for p in ws.rglob('*') if p.is_file() and p.name != 'gallery.html'}
    assert before == after


def test_cli_gallery(project):
    ws, _, _ = project
    proc = subprocess.run([sys.executable, '-B', str(CLI), 'gallery', '--workspace', str(ws)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out['status'] == 'gallery_written' and (ws / 'gallery.html').is_file()


def test_status_versions_carry_scene_title(project, png_factory):
    ws, _, cards = project
    record(ws, cards['studio'], 1, png_factory)
    version = projects.status(ws)['series'][0]['sets'][0]['shots'][0]['versions'][0]
    assert version['title'] == cards['studio']['shots'][0]['title']


def test_write_replaces_symlink_instead_of_following_it(project, tmp_path):
    ws, _, _ = project
    outside = tmp_path / 'outside.txt'
    outside.write_text('keep', encoding='utf-8')
    (ws / 'gallery.html').symlink_to(outside)
    gallery.build(ws)
    assert outside.read_text(encoding='utf-8') == 'keep'
    assert not (ws / 'gallery.html').is_symlink()
    (ws / 'gallery.html').unlink()
    before = (ws / 'project.json').read_bytes()
    (ws / 'gallery.html').symlink_to(ws / 'project.json')
    gallery.build(ws)
    assert (ws / 'project.json').read_bytes() == before


def test_links_cannot_become_javascript_urls(project):
    ws, _, _ = project
    (ws / 'javascript:alert(1)').write_text('x', encoding='utf-8')
    (ws / 'captions').mkdir()
    (ws / 'captions/studio.md').symlink_to(ws / 'javascript:alert(1)')
    gallery.build(ws)
    html = (ws / 'gallery.html').read_text(encoding='utf-8')
    assert 'href="javascript:' not in html
    assert re.findall(r'(?:href|src)="([^"]*)"', html) and all(
        ':' not in u for u in re.findall(r'(?:href|src)="([^"]*)"', html))
