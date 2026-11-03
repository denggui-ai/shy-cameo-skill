"""Build a Codex plugin candidate from an explicit reviewed allowlist."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

# Optional body-reference images ship separately; keep the default runtime below 5 MB.
LIMIT_BYTES = 5_000_000
EXTRAS = {"release/plugin.json", "release/icon.svg", "release/USER-GUIDE.html", "release/INSTALL.md", "LICENSE"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
FORBIDDEN = {".git", ".env", "__pycache__", ".pytest_cache", ".venv", "node_modules", "tests", "evals", "evidence"}


def safe_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("unsafe path")
    path = PurePosixPath(value)
    parts = value.split("/")
    if path.is_absolute() or any(p in {"", ".", ".."} for p in parts):
        raise ValueError("unsafe path")
    for part in parts:
        if (part.endswith((".", " ")) or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or part.split(".")[0].upper() in RESERVED):
            raise ValueError("unsafe path")
    return path


def build(source: Path, output: Path, allowlist: Path) -> dict:
    source = source.resolve()
    entries = json.loads(allowlist.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError("invalid allowlist length")
    prepared, seen, total = [], set(), 0
    for entry in entries:
        src_rel, dst_rel = safe_path(entry["source"]), safe_path(entry["destination"])
        key = str(dst_rel).casefold()
        if key in seen:
            raise ValueError("destination collision")
        seen.add(key)
        if (str(src_rel) not in EXTRAS and not str(src_rel).startswith("skills/shy-cameo/")):
            raise ValueError("source not permitted")
        if (set(src_rel.parts) & FORBIDDEN or set(dst_rel.parts) & FORBIDDEN or src_rel.suffix == ".pyc"
                or any(part.startswith(".env") for part in src_rel.parts)):
            raise ValueError("source not permitted")
        if src_rel.suffix in {".png", ".jpg", ".jpeg", ".webp"} and not str(src_rel).startswith((
                "skills/shy-cameo/references/photo-guide/",
                "skills/shy-cameo/references/body-reference/images/")):
            raise ValueError("image source not permitted")
        file = source.joinpath(*src_rel.parts)
        if any(p.is_symlink() for p in [file, *file.parents] if p != source.parent):
            raise ValueError("symbolic link not permitted")
        if not file.is_file() or source not in file.resolve().parents:
            raise ValueError("source is not a regular file under source root")
        if file.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("release size limit exceeded")
        raw = file.read_bytes()
        total += len(raw)
        if len(raw) > 5 * 1024 * 1024 or total > LIMIT_BYTES:
            raise ValueError("release size limit exceeded")
        if src_rel.suffix in {".py", ".md", ".json", ".yaml", ".html", ".svg"}:
            text = raw.decode("utf-8")
            if re.search(r"/Users/|/home/[^\s/]+/|[A-Z]:\\Users\\", text):
                raise ValueError("developer home path not permitted")
        prepared.append((dst_rel, raw))
    if ".codex-plugin/plugin.json" not in seen or "skills/shy-cameo/skill.md" not in seen or "user-guide.html" not in seen:
        raise ValueError("required release files missing")
    plugin = json.loads(dict((str(p), raw) for p, raw in prepared)[".codex-plugin/plugin.json"])
    if (plugin.get("name") != "shy-cameo"
            or plugin.get("version") not in {"1.0.0-rc.1", "1.0.0-beta.1", "1.0.0-beta.2", "1.0.0-beta.3", "1.0.0", "1.0.1", "1.0.2-rc.1", "1.0.2-rc.2", "1.0.3-dev.20261102.1", "1.0.3-rc.1", "1.1.0-rc.1"}):
        raise ValueError("unsupported candidate version")
    if not isinstance(plugin.get("description"), str) or not 1 <= len(plugin["description"]) <= 4000:
        raise ValueError("plugin description missing or invalid")
    author = plugin.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not 1 <= len(author["name"]) <= 120:
        raise ValueError("plugin author.name missing or invalid")
    if plugin.get("skills") != "./skills/":
        raise ValueError("plugin skills must point to the staged skills directory")
    interface = plugin.get("interface")
    if not isinstance(interface, dict):
        raise ValueError("plugin interface missing")
    for key, limit in {"displayName": 30, "shortDescription": 30, "longDescription": 4000,
                       "developerName": 80, "category": 80}.items():
        value = interface.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise ValueError(f"plugin interface.{key} missing or invalid")
    caps = interface.get("capabilities")
    if not isinstance(caps, list) or len(caps) > 20 or any(not isinstance(v, str) or len(v) > 120 for v in caps):
        raise ValueError("plugin interface.capabilities missing or invalid")
    for key in ["logo", "composerIcon"]:
        icon = interface.get(key)
        if not isinstance(icon, str) or not icon.startswith("./"):
            raise ValueError(f"plugin interface.{key} must be a bundled relative path")
        if str(safe_path(icon[2:])).casefold() not in seen:
            raise ValueError(f"plugin interface.{key} file not included")
    # Validate everything before creating output; an existing build is never overwritten.
    output.mkdir(parents=True, exist_ok=False)
    stage = output / "stage" / "shy-cameo"
    rows = []
    for relative, raw in prepared:
        dest = stage.joinpath(*relative.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        rows.append({"path": str(relative), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    provenance = {"version": plugin["version"], "status": "candidate", "files": rows,
                  "limitations": (["local compile-edit package update; installation and remote publication are recorded separately", "one synthetic cuff-color edit accepted and selected; automatic call audit remains unverified; no pixel-exact preservation claim", "isolated CLI model first-use lacks authentication; copied-workspace absolute-path issue remains unresolved", "native image pre-submit hard blocking is not provided; other hosts and platforms unverified"] if plugin["version"] == "1.0.2-rc.2" else ["candidate artifact; packaging does not establish installation or publication status", "scoped visual and text evaluation only; identity, body proportions, material precision and prop physical plausibility remain limited", "native image pre-submit hard blocking is not provided; other hosts unverified"] if plugin["version"] == "1.0.2-rc.1" else ["native image pre-submit hard blocking is not provided; zero-submit live-tool testing deferred", "verified visual evidence: historical Jigong five-shot sample only; animation examples compile offline but have no generated-image acceptance; other hosts and subjects unverified"] if plugin["version"] in {"1.0.0", "1.0.1"} else ["native-image authorization-boundary acceptance pending", "other hosts and platforms unverified", "experimental; not stable v1.0"])}
    if plugin["version"] == "1.0.3-dev.20261102.1":
        provenance["limitations"] = [
            "local discovery-test candidate; not installed or published by this build",
            "automatic discovery M01 x3 and M02 x3 awaits owner execution",
            "optional body-reference images and comparison page ship separately; text fallback remains available",
            "no new model or image-provider calls; no new visual-quality or lifecycle verification",
        ]
    elif plugin["version"] == "1.0.3-rc.1":
        provenance["limitations"] = [
            "release preparation does not establish remote publication or installation status",
            "the unchanged skill entrypoint passed six pre-release discovery sessions: M01 3/3 loaded, M02 0/3 loaded; other prompts, hosts and devices remain unverified",
            "optional body-reference images and comparison page ship separately; text fallback remains available",
            "no new image-provider verification; identity, precise body control and pixel-exact editing remain limited",
            "native image pre-submit hard blocking is not provided; incomplete call traces remain unverifiable",
        ]
    elif plugin["version"] == "1.1.0-rc.1":
        provenance["limitations"] = [
            "release preparation does not establish remote publication or installation status",
            "concert and band-interaction features remain experimental; accepted virtual-subject examples do not establish stable real-person likeness or precise instrument anatomy",
            "prior discovery results belong to v1.0.3-rc.1; this release has no new implicit-trigger, fresh-host or model first-use verification",
            "optional body-reference gallery 20261102 is unchanged and ships separately; text fallback remains available",
            "audience merchandise guidance and additional band-interaction text evals remain unverified; packaging adds no image-provider calls",
            "native image pre-submit hard blocking is not provided; incomplete call traces remain unverifiable",
        ]
    (stage / "PROVENANCE.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / f"shy-cameo-{plugin['version']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                bundle.write(file, str(file.relative_to(stage.parent)))
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="utf-8")
    return {"status": "candidate", "stage": str(stage), "archive": str(archive), "checksum": str(checksum), "file_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["source", "output", "allowlist"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.source, args.output, args.allowlist)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
