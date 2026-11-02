"""Package reviewed local body-reference assets. No downloads or installation."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from build_v1_release import safe_path


def build(assets: Path, allowlist: Path, output: Path) -> dict:
    assets = assets.resolve()
    manifest = json.loads(allowlist.read_text(encoding="utf-8"))
    name = safe_path(manifest["bundle"])
    if len(name.parts) != 1:
        raise ValueError("bundle name must be a filename")
    entries = manifest["files"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("invalid asset list")
    prepared, seen, total = [], set(), 0
    for entry in entries:
        rel = safe_path(entry["path"])
        if not (str(rel) == "compare.html" or len(rel.parts) == 2 and rel.parts[0] == "images"):
            raise ValueError("asset outside gallery")
        if str(rel).casefold() in seen:
            raise ValueError("duplicate asset")
        seen.add(str(rel).casefold())
        path = assets.joinpath(*rel.parts)
        if any(assets.joinpath(*rel.parts[:i]).is_symlink() for i in range(1, len(rel.parts) + 1)):
            raise ValueError("symbolic link not permitted")
        if not path.is_file() or path.stat().st_size > 5_000_000:
            raise ValueError("missing or oversized asset: " + str(rel))
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("asset digest mismatch: " + str(rel))
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise ValueError("gallery too large")
        prepared.append(("body-reference/" + str(rel), raw))
    output.mkdir(parents=True, exist_ok=False)
    archive = output / (str(name) + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path, raw in sorted(prepared):
            info = zipfile.ZipInfo(path, date_time=(2026, 11, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, raw)
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
    return {"status": "packaged", "archive": str(archive), "checksum": str(checksum),
            "files": len(prepared), "uncompressed_bytes": total, "archive_bytes": archive.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "allowlist", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.assets, args.allowlist, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
