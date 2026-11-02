import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_body_reference_bundle import build


def asset_source(tmp_path):
    assets = tmp_path / "assets"
    (assets / "images").mkdir(parents=True)
    rows = []
    for name, raw in {"images/B01-front.png": b"reviewed-image", "compare.html": b'<img src="images/B01-front.png">'}.items():
        (assets / name).write_bytes(raw)
        rows.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    (assets / "images/private.png").write_bytes(b"not-for-release")
    manifest = tmp_path / "allowlist.json"
    manifest.write_text(json.dumps({"bundle": "gallery-test", "files": rows}))
    return assets, manifest


def test_gallery_bundle_restores_reviewed_bytes_without_unlisted_files(tmp_path):
    assets, manifest = asset_source(tmp_path)
    result = build(assets, manifest, tmp_path / "out")
    with zipfile.ZipFile(result["archive"]) as archive:
        assert set(archive.namelist()) == {"body-reference/images/B01-front.png", "body-reference/compare.html"}
        destination = tmp_path / "skill/references"
        archive.extractall(destination)
    for row in json.loads(manifest.read_text())["files"]:
        assert hashlib.sha256((destination / "body-reference" / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    assert Path(result["checksum"]).read_text().split()[0] == hashlib.sha256(Path(result["archive"]).read_bytes()).hexdigest()


@pytest.mark.parametrize("failure", ["changed", "missing", "symlink"])
def test_gallery_blocks_unverified_assets_before_creating_output(tmp_path, failure):
    assets, manifest = asset_source(tmp_path)
    image = assets / "images/B01-front.png"
    if failure == "changed":
        image.write_bytes(b"modified")
    else:
        image.unlink()
        if failure == "symlink":
            image.symlink_to(assets / "images/private.png")
    with pytest.raises(ValueError):
        build(assets, manifest, tmp_path / "out")
    assert not (tmp_path / "out").exists()
