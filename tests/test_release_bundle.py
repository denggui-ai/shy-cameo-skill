"""The private release builder must never copy unchecked source files."""
import json
import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BUILDER = Path(__file__).resolve().parents[1] / "scripts" / "build_v1_release.py"
ROOT = BUILDER.parent.parent


def source_tree(tmp_path):
    src = tmp_path / "source"
    for name, text in {
        "skills/shy-cameo/SKILL.md": "---\nname: shy-cameo\ndescription: example\n---\n",
        "release/plugin.json": json.dumps({"name": "shy-cameo", "version": "1.0.0-rc.1",
            "description": "Private candidate", "author": {"name": "Test"}, "skills": "./skills/",
            "interface": {"displayName": "Test", "shortDescription": "Test", "longDescription": "Test",
                "developerName": "Test", "category": "Productivity", "capabilities": [],
                "logo": "./assets/icon.svg", "composerIcon": "./assets/icon.svg"}}),
        "release/icon.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"/>',
        "release/USER-GUIDE.html": "<!doctype html><title>Guide</title>",
        "LICENSE": "MIT",
    }.items():
        file = src / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    return src


def run_builder(tmp_path, src, entries):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps(entries))
    result = subprocess.run([sys.executable, "-B", str(BUILDER), "--source", str(src),
                             "--output", str(tmp_path / "out"), "--allowlist", str(allowlist)],
                            capture_output=True, text=True)
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result, payload


def core_entries():
    return [
        {"source": "skills/shy-cameo/SKILL.md", "destination": "skills/shy-cameo/SKILL.md"},
        {"source": "release/plugin.json", "destination": ".codex-plugin/plugin.json"},
        {"source": "release/USER-GUIDE.html", "destination": "USER-GUIDE.html"},
        {"source": "release/icon.svg", "destination": "assets/icon.svg"},
    ]


def test_release_copies_only_allowlisted_files(tmp_path):
    src = source_tree(tmp_path)
    (src / "skills/shy-cameo/private-note.md").write_text("private")
    result, data = run_builder(tmp_path, src, core_entries())
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(data["archive"]) as archive:
        assert "shy-cameo/skills/shy-cameo/SKILL.md" in archive.namelist()
        assert not any("private-note" in name for name in archive.namelist())
        assert archive.read("shy-cameo/skills/shy-cameo/SKILL.md") == (src / "skills/shy-cameo/SKILL.md").read_bytes()
    assert Path(data["checksum"]).is_file()
    assert Path(data["checksum"]).read_text().split()[0] == hashlib.sha256(Path(data["archive"]).read_bytes()).hexdigest()


def test_release_rejects_incomplete_plugin_manifest(tmp_path):
    src = source_tree(tmp_path)
    file = src / "release/plugin.json"
    meta = json.loads(file.read_text())
    del meta["interface"]
    file.write_text(json.dumps(meta))
    result, data = run_builder(tmp_path, src, core_entries())
    assert result.returncode == 2
    assert "interface" in data.get("error", "")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("version", ["1.0.0-beta.1", "1.0.0-beta.2", "1.0.0-beta.3", "1.0.0", "1.0.1", "1.0.2-rc.1", "1.0.3-dev.20261102.1", "1.0.3-rc.1", "1.1.0-rc.1", "1.1.0"])
def test_release_archive_and_provenance_use_manifest_version(tmp_path, version):
    src = source_tree(tmp_path)
    manifest = src / "release/plugin.json"
    plugin = json.loads(manifest.read_text())
    plugin["version"] = version
    manifest.write_text(json.dumps(plugin))
    result, data = run_builder(tmp_path, src, core_entries())
    assert result.returncode == 0, result.stderr
    assert Path(data["archive"]).name == f"shy-cameo-{version}.zip"
    with zipfile.ZipFile(data["archive"]) as archive:
        provenance = json.loads(archive.read("shy-cameo/PROVENANCE.json"))
        assert provenance["version"] == plugin["version"]
        if version == "1.0.3-dev.20261102.1":
            assert provenance["status"] == "candidate"
            assert any("awaits owner execution" in item for item in provenance["limitations"])
        if version == "1.0.3-rc.1":
            assert provenance["status"] == "candidate"
            assert any("M01 3/3 loaded, M02 0/3 loaded" in item for item in provenance["limitations"])
            assert not any("awaits owner execution" in item for item in provenance["limitations"])
        if version in {"1.1.0-rc.1", "1.1.0"}:
            assert provenance["status"] == "candidate"
            assert any("concert and band-interaction features remain experimental" in item
                       for item in provenance["limitations"])
            assert any("prior discovery results belong to v1.0.3-rc.1" in item
                       for item in provenance["limitations"])
            assert not any("M01 3/3 loaded" in item for item in provenance["limitations"])
        if version in {"1.0.0", "1.0.1"}:
            assert not any("not stable" in item for item in provenance["limitations"])
            assert any("hard blocking" in item for item in provenance["limitations"])


def test_release_rejects_unreviewed_version_before_writing(tmp_path):
    src = source_tree(tmp_path)
    manifest = src / "release/plugin.json"
    plugin = json.loads(manifest.read_text())
    plugin["version"] = "2.0.0"
    manifest.write_text(json.dumps(plugin))
    result, data = run_builder(tmp_path, src, core_entries())
    assert result.returncode == 2
    assert "unsupported candidate version" in data["error"]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("entries, reason", [
    ([{"source": "../outside", "destination": "SKILL.md"}], "unsafe path"),
    ([{"source": "LICENSE", "destination": "../outside"}], "unsafe path"),
    ([{"source": "LICENSE", "destination": "CON.txt"}], "unsafe path"),
    ([{"source": "LICENSE", "destination": "A.txt"}, {"source": "LICENSE", "destination": "a.TXT"}], "collision"),
    ([{"source": "private/photo.png", "destination": "assets/photo.png"}], "not permitted"),
])
def test_release_rejects_unsafe_entries_before_writing(tmp_path, entries, reason):
    src = source_tree(tmp_path)
    result, data = run_builder(tmp_path, src, entries)
    assert result.returncode == 2
    assert reason in data.get("error", "")
    assert not (tmp_path / "out").exists()


def test_release_rejects_symbolic_link(tmp_path):
    src = source_tree(tmp_path)
    link = src / "skills/shy-cameo/link.md"
    link.symlink_to(src / "LICENSE")
    result, data = run_builder(tmp_path, src, [{"source": str(link.relative_to(src)), "destination": "link.md"}])
    assert result.returncode == 2
    assert "symbolic link" in data.get("error", "")
    assert not (tmp_path / "out").exists()


def test_body_reference_image_requires_explicit_allowlist_and_keeps_original_bytes(tmp_path):
    src = source_tree(tmp_path)
    approved = "skills/shy-cameo/references/body-reference/images/T01-front.png"
    private = "skills/shy-cameo/private-photo.png"
    path = src / approved; path.parent.mkdir(parents=True)
    path.write_bytes(b"accepted-image-bytes")
    (src / private).write_bytes(b"private-image")
    result, data = run_builder(tmp_path, src, core_entries() + [{"source":approved,"destination":approved}])
    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(data['archive']) as archive:
        assert archive.read('shy-cameo/' + approved) == path.read_bytes()
        assert 'shy-cameo/' + private not in archive.namelist()


@pytest.mark.parametrize("artifact", ["plugin", "public-source"])
def test_actual_release_cli_starts_without_source_checkout(tmp_path, artifact):
    """The distributed artifact must contain the CLI's imports and linked runtime guides."""
    out = tmp_path / "out"
    if artifact == "plugin":
        cmd = [sys.executable, "-B", str(BUILDER), "--source", str(ROOT), "--output", str(out),
               "--allowlist", str(ROOT / "release/runtime-allowlist.json")]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        archive = Path(json.loads(result.stdout)["archive"])
        assert archive.stat().st_size < 5_000_000
        unpacked = tmp_path / "unpacked"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(unpacked)
        skill = unpacked / "shy-cameo/skills/shy-cameo"
    else:
        cmd = [sys.executable, "-B", str(ROOT / "scripts/export_public_source.py"),
               "--source", str(ROOT), "--output", str(out),
               "--allowlist", str(ROOT / "release/public-source-allowlist.json")]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        skill = out / "skills/shy-cameo"

    reference = skill / "references/body-reference"
    assert not (reference / "images").exists()
    assert not (reference / "compare.html").exists()
    assert sum(p.stat().st_size for p in skill.rglob("*") if p.is_file()) < 5_000_000
    for name in ("manifest.json", "expansion-manifest.json"):
        manifest = json.loads((reference / name).read_text())
        assert manifest["status"] == "user_accepted" and manifest["items"]

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    for args in (["--help"], ["validate-library"]):
        result = subprocess.run([sys.executable, "-B", str(skill / "scripts/cli.py"), *args],
                                capture_output=True, text=True, cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        if args == ["validate-library"]:
            assert json.loads(result.stdout) == {"ok": True, "errors": []}
    for name in ("generation.md", "opening-and-topics.md", "stage-and-concerts.md"):
        assert (skill / "references" / name).is_file()
    # A draft can still be checked with no gallery, photos, login, or project state.
    draft = json.loads((ROOT / "tests/fixtures/animation/set-original-fox-inn.json").read_text())
    draft["status"] = "unverified"
    for shot in draft["shots"]:
        shot["status"] = "unverified"
    card = tmp_path / "draft.json"
    card.write_text(json.dumps(draft))
    result = subprocess.run([sys.executable, "-B", str(skill / "scripts/cli.py"),
                             "check-pose-variety", "--set-card", str(card)],
                            capture_output=True, text=True, cwd=tmp_path, env={"PATH": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["advisory_only"] is True
    assert not (tmp_path / "outputs").exists()
