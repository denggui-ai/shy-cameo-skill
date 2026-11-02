"""A public source export must work without shipping private development state."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "scripts/export_public_source.py"


def fixture_source(tmp_path):
    src = tmp_path / "source"
    contents = {
        "README.md": "Public beta",
        "LICENSE": "MIT",
        "skills/shy-cameo/SKILL.md": "Public skill",
        "scripts/export_public_source.py": EXPORTER.read_text(),
        "scripts/build_v1_release.py": (ROOT / "scripts/build_v1_release.py").read_text(),
        "release/plugin.json": json.dumps({"name": "shy-cameo", "version": "1.0.2-rc.1"}),
        "release/runtime-allowlist.json": json.dumps([
            {"source": "skills/shy-cameo/SKILL.md", "destination": "skills/shy-cameo/SKILL.md"}]),
        "tests/fakes/fake_codex": "#!/bin/sh\nexit 0\n",
        "release/style-keywords.json": (ROOT / "release/style-keywords.json").read_text(encoding="utf-8"),
    }
    for rel, text in contents.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (src / "tests/fakes/fake_codex").chmod(0o755)
    entries = [{"source": p, "destination": p} for p in contents]
    (src / "public-notes.md").write_text("Public changes only")
    entries.append({"source": "public-notes.md", "destination": "CHANGELOG.md"})
    entries.append({"source": "release/public-source-allowlist.json",
                    "destination": "release/public-source-allowlist.json"})
    return src, entries


def run_export(tmp_path, src, entries):
    manifest = src / "release/public-source-allowlist.json"
    manifest.parent.mkdir(exist_ok=True)
    manifest.write_text(json.dumps(entries))
    result = subprocess.run([sys.executable, "-B", str(EXPORTER), "--source", str(src),
                             "--output", str(tmp_path / "public"), "--allowlist", str(manifest)],
                            capture_output=True, text=True)
    return result, json.loads(result.stdout)


def test_export_is_text_only_without_history_and_can_reexport(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / ".git").mkdir()
    (src / ".git/private-history").write_text("private")
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 0, data
    public = Path(data["source_directory"])
    assert not (public / ".git").exists()
    assert (public / "CHANGELOG.md").read_text() == "Public changes only"
    assert not (public / "public-notes.md").exists()
    assert (public / "tests/fakes/fake_codex").stat().st_mode & 0o111
    manifest = json.loads((public / "PUBLIC-EXPORT.json").read_text())
    assert not manifest["git_history_included"] and not manifest["images_included"]
    assert manifest["version"] == json.loads((public / "release/plugin.json").read_text())["version"]
    again = subprocess.run([sys.executable, "-B", str(public / "scripts/export_public_source.py"),
                            "--source", str(public), "--output", str(tmp_path / "again"),
                            "--allowlist", str(public / "release/public-source-allowlist.json")],
                           capture_output=True, text=True)
    assert again.returncode == 0, again.stdout


@pytest.mark.parametrize("name,text", [
    ("photo.png", "not a photograph"),
    ("evidence/notes.md", "internal"),
    (".env", "placeholder"),
    ("note.md", "/" + "Users" + "/" + "sample-person" + "/private"),
    ("note.md", "gh" + "p_" + "x" * 40),
])
def test_export_blocks_private_assets_before_creating_output(tmp_path, name, text):
    src, entries = fixture_source(tmp_path)
    p = src / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    entries.append({"source": name, "destination": name})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()
    assert text not in result.stdout


def test_public_export_excludes_evidence_and_migration_backups(tmp_path):
    def private(path):
        path = PurePosixPath(path.lower())
        return 'evidence' in path.parts or path.match('*.pre-relative-paths-*.bak')

    # Lock the reviewed manifest as well as the exporter behavior: neither end may leak.
    actual = json.loads((ROOT / 'release/public-source-allowlist.json').read_text())
    assert not [(e['source'], e['destination']) for e in actual
                if any(private(e[k]) for k in ('source', 'destination'))]
    src, entries = fixture_source(tmp_path)
    excluded = ['evidence/p0/REPORT.md', 'records/set.json.pre-relative-paths-' + 'a' * 64 + '.bak']
    marker = 'PRIVATE_P0_EVIDENCE_SENTINEL'
    for name in excluded:
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marker)
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 0, data
    public = tmp_path / 'public'
    files = [p for p in public.rglob('*') if p.is_file()]
    assert not any(private(p.relative_to(public).as_posix()) for p in files)
    assert all(marker.encode() not in p.read_bytes() for p in files)
    # Even an accidentally added or renamed allowlist entry must fail before writing.
    attempts = [{'source': name, 'destination': 'leaked.md'} for name in excluded]
    attempts += [{'source': 'README.md', 'destination': name} for name in excluded]
    for index, entry in enumerate(attempts):
        attempt = tmp_path / f'blocked-{index}'
        result, data = run_export(attempt, src, entries + [entry])
        assert result.returncode == 2 and data['status'] == 'blocked', (entry, data)
        assert not (attempt / 'public').exists()
        assert marker not in result.stdout


def test_export_blocks_symlink_and_preserves_existing_output(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "link.md").symlink_to(src / "README.md")
    entries.append({"source": "link.md", "destination": "link.md"})
    result, _ = run_export(tmp_path, src, entries)
    assert result.returncode == 2
    assert not (tmp_path / "public").exists()
    entries.pop()
    result, _ = run_export(tmp_path, src, entries)
    assert result.returncode == 0
    (tmp_path / "public/keep.md").write_text("keep")
    result, _ = run_export(tmp_path, src, entries)
    assert result.returncode == 2
    assert (tmp_path / "public/keep.md").read_text() == "keep"


def test_export_blocks_destination_traversal_and_case_collision(tmp_path):
    src, entries = fixture_source(tmp_path)
    entries.append({"source": "LICENSE", "destination": "../outside.txt"})
    result, _ = run_export(tmp_path, src, entries)
    assert result.returncode == 2
    assert not (tmp_path / "public").exists()
    entries[-1]["destination"] = "readme.MD"
    result, _ = run_export(tmp_path, src, entries)
    assert result.returncode == 2
    assert not (tmp_path / "public").exists()


def test_offline_case_links_are_explicitly_omitted_not_broken():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from export_public_source import offline_document
    text = '[能力](CAPABILITIES.md) ![图](../assets/a.png) <a href="../assets/case/README.md">案例</a><img src="../assets/b.png"> [官网](https://example.com)'
    result = offline_document(text, 'release/CASE-GALLERY.md', {'release/capabilities.md'})
    assert '[能力](CAPABILITIES.md)' in result
    assert '../assets/' not in result
    assert '素材未包含于源码包' in result and 'https://example.com' in result


def test_export_scans_file_renamed_onto_keyword_list(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "evil.md").write_text("x" + "圆" + "耳" + "x", encoding="utf-8")
    entries = [e for e in entries if e["source"] != "release/style-keywords.json"]
    entries.append({"source": "evil.md", "destination": "release/style-keywords.json"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("word", ["圆" + "耳", "86" + " 版风格", "94" + "版风格"])
def test_export_blocks_costume_keyword(tmp_path, word):
    src, entries = fixture_source(tmp_path)
    (src / "note.md").write_text("some text " + word + " more", encoding="utf-8")
    entries.append({"source": "note.md", "destination": "note.md"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()
    assert word not in result.stdout


def test_export_allows_character_names_without_costume(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "note.md").write_text("和功夫熊猫阿宝、漩涡鸣人同框，原著孙悟空戴凤翅紫金冠", encoding="utf-8")
    entries.append({"source": "note.md", "destination": "note.md"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 0, data


def test_real_allowlist_exports_clean(tmp_path):
    result = subprocess.run([sys.executable, "-B", str(EXPORTER), "--source", str(ROOT),
                             "--output", str(tmp_path / "public"),
                             "--allowlist", str(ROOT / "release/public-source-allowlist.json")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
    public = tmp_path / "public"
    rebuilt = subprocess.run([sys.executable, "-B", str(public / "scripts/build_v1_release.py"),
                              "--source", str(public), "--output", str(tmp_path / "rebuilt"),
                              "--allowlist", str(public / "release/runtime-allowlist.json")],
                             capture_output=True, text=True, cwd=tmp_path)
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr


def test_export_blocks_missing_runtime_dependency_before_creating_output(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "release/runtime-allowlist.json").write_text(json.dumps([
        {"source": "skills/shy-cameo/missing.json", "destination": "skills/shy-cameo/missing.json"}]))
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2
    assert data["error"].startswith("runtime build source missing from export")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("case", ["valid", "missing_digest", "changed_bytes", "renamed", "wrong_kind"])
def test_synthetic_reference_export_requires_reviewed_bytes_and_preserves_reexport(tmp_path, case):
    src, entries = fixture_source(tmp_path)
    rel = "skills/shy-cameo/references/body-reference/images/B01-front.png"
    path = src / rel
    path.parent.mkdir(parents=True)
    raw = b"\x89PNG-synthetic-reference"
    path.write_bytes(raw)
    item = {"source": rel, "destination": rel, "asset_kind": "synthetic_reference",
            "sha256": hashlib.sha256(raw).hexdigest()}
    if case == "missing_digest":
        item.pop("sha256")
    elif case == "changed_bytes":
        path.write_bytes(raw + b"changed")
    elif case == "renamed":
        item["destination"] = rel.replace("B01", "B02")
    elif case == "wrong_kind":
        item["asset_kind"] = "unreviewed"
    entries.append(item)
    result, data = run_export(tmp_path, src, entries)
    if case != "valid":
        assert result.returncode == 2
        assert data["error"].startswith("reference image without reviewed digest")
        assert not (tmp_path / "public").exists()
        return
    assert result.returncode == 0, data
    public = tmp_path / "public"
    assert (public / rel).read_bytes() == raw
    again = subprocess.run([sys.executable, "-B", str(public / "scripts/export_public_source.py"),
                            "--source", str(public), "--output", str(tmp_path / "again"),
                            "--allowlist", str(public / "release/public-source-allowlist.json")],
                           capture_output=True, text=True)
    assert again.returncode == 0, again.stdout
    assert (tmp_path / "again" / rel).read_bytes() == raw


def showcase_set(src, entries, **tweak):
    """Build a synthetic showcase set (a few bytes, no real photo) and list it for export."""
    import hashlib
    data = b"\x89PNG-synthetic"
    d = src / "assets/showcase/set1"
    d.mkdir(parents=True)
    (d / "01.png").write_bytes(data)
    manifest = {"set_id": "set1",
                "images": [{"file": "01.png", "sha256": hashlib.sha256(data).hexdigest()}],
                "gates": {"likeness_ok": True, "boundary_ok": True, "owner_consent_public_face": True},
                "approved_by": "owner", "approved_on": "2026-10-26"}
    manifest.update(tweak)
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    rel = "assets/showcase/set1/"
    entries.append({"source": rel + "01.png", "destination": rel + "01.png"})
    return data, rel


@pytest.mark.parametrize("case", ["no_manifest", "manifest_not_listed", "gate_false",
                                  "gate_string_true", "sha_mismatch", "svg_no_manifest"])
def test_showcase_image_without_manifest_is_blocked(tmp_path, case):
    src, entries = fixture_source(tmp_path)
    tweak = {}
    if case == "gate_false":
        tweak["gates"] = {"likeness_ok": True, "boundary_ok": False, "owner_consent_public_face": True}
    if case == "gate_string_true":
        tweak["gates"] = {"likeness_ok": "true", "boundary_ok": True, "owner_consent_public_face": True}
    if case == "sha_mismatch":
        tweak["images"] = [{"file": "01.png", "sha256": "0" * 64}]
    if case == "svg_no_manifest":
        d = src / "assets/showcase/set2"
        d.mkdir(parents=True)
        (d / "a.svg").write_text("<svg/>", encoding="utf-8")
        entries.append({"source": "assets/showcase/set2/a.svg", "destination": "assets/showcase/set2/a.svg"})
    else:
        _, rel = showcase_set(src, entries, **tweak)
        if case == "no_manifest":
            (src / (rel + "manifest.json")).unlink()
        if case not in ("manifest_not_listed", "no_manifest"):
            entries.append({"source": rel + "manifest.json", "destination": rel + "manifest.json"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert data["error"].startswith("showcase image without passed gates")
    assert not (tmp_path / "public").exists()


def test_showcase_image_with_passed_gates_exports(tmp_path):
    src, entries = fixture_source(tmp_path)
    data, rel = showcase_set(src, entries)
    entries.append({"source": rel + "manifest.json", "destination": rel + "manifest.json"})
    result, out = run_export(tmp_path, src, entries)
    assert result.returncode == 0, out
    public = Path(out["source_directory"])
    assert (public / rel / "01.png").read_bytes() == data
    assert json.loads((public / "PUBLIC-EXPORT.json").read_text())["images_included"] is True


def test_showcase_image_renamed_to_text_still_gets_full_scan(tmp_path):
    import hashlib
    src, entries = fixture_source(tmp_path)
    body = ("/" + "Users" + "/" + "sample-person" + "/private " + "ghp" + "_" + "a" * 36).encode()
    d = src / "assets/showcase/set1"
    d.mkdir(parents=True)
    (d / "note.png").write_bytes(body)
    (d / "note.md").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (d / "manifest.json").write_text(json.dumps({
        "set_id": "set1", "approved_by": "owner", "approved_on": "2026-10-26",
        "gates": {"likeness_ok": True, "boundary_ok": True, "owner_consent_public_face": True},
        "images": [{"file": "note.png", "sha256": digest}, {"file": "note.md", "sha256": digest}]}),
        encoding="utf-8")
    rel = "assets/showcase/set1/"
    entries.append({"source": rel + "note.png", "destination": rel + "note.md"})
    entries.append({"source": rel + "manifest.json", "destination": rel + "manifest.json"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()


def test_export_blocks_other_file_replacing_keyword_list(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "empty.json").write_text(json.dumps({"literals": [], "patterns": []}), encoding="utf-8")
    entries = [e for e in entries if e["source"] != "release/style-keywords.json"]
    entries.append({"source": "empty.json", "destination": "release/style-keywords.json"})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("destination", ["release/STYLE-keywords.json", "Release/style-keywords.json"])
def test_export_blocks_case_variant_replacing_keyword_list(tmp_path, destination):
    # Case-insensitive filesystems resolve these to the real list on re-export.
    src, entries = fixture_source(tmp_path)
    (src / "weak.json").write_text(json.dumps({"literals": ["☃"], "patterns": ["^$"]}), encoding="utf-8")
    entries = [e for e in entries if e["source"] != "release/style-keywords.json"]
    entries.append({"source": "weak.json", "destination": destination})
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()


def test_export_blocks_empty_keyword_list_itself(tmp_path):
    src, entries = fixture_source(tmp_path)
    (src / "release/style-keywords.json").write_text(
        json.dumps({"literals": [], "patterns": ["x{3}"]}), encoding="utf-8")
    result, data = run_export(tmp_path, src, entries)
    assert result.returncode == 2 and data["status"] == "blocked"
    assert not (tmp_path / "public").exists()
