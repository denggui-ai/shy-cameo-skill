"""Export reviewed source and explicitly approved assets without private history."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import posixpath
from urllib.parse import urlsplit, unquote
from pathlib import Path

from build_v1_release import safe_path

ALLOWED_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".html", ".svg"}
ALLOWED_EXTENSIONLESS = {"LICENSE", ".gitignore", "CODEOWNERS", "fake_codex"}
FORBIDDEN = {".git", ".env", ".venv", ".pytest_cache", "__pycache__", "node_modules",
             "evidence", "docs", "coshoot-workspace"}
HOME_PATH = re.compile(r"/(?:Users|home)/[\w.-]+/")
SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
                    r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bsk-[A-Za-z0-9_-]{32,}\b")
STYLE_KEYWORDS = "release/style-keywords.json"
SHOWCASE_DIR = "assets/showcase"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SHOWCASE_GATES = ("likeness_ok", "boundary_ok", "owner_consent_public_face")
REFERENCE_IMAGES = "skills/shy-cameo/references/body-reference/images"
LIMIT_BYTES = 64 * 1024 * 1024


def load_style_rules(source: Path) -> list:
    """Compile the public costume-keyword list; the list file itself is exempt."""
    try:
        data = json.loads(source.joinpath(*STYLE_KEYWORDS.split("/")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("style keyword list missing")
    if not (isinstance(data, dict) and all(isinstance(data.get(k), list) and data[k]
                                           for k in ("literals", "patterns"))):
        raise ValueError("style keyword list missing")
    return ([re.compile(re.escape(w)) for w in data["literals"]]
            + [re.compile(p) for p in data["patterns"]])


def in_showcase(path) -> bool:
    return "/".join(path.parts[:2]) == SHOWCASE_DIR


def is_reference_image(path) -> bool:
    return str(path.parent) == REFERENCE_IMAGES and path.suffix.lower() in IMAGE_SUFFIXES | {".svg"}


def check_reference_image(entry: dict, src, dst, raw: bytes) -> None:
    """Only the reviewed synthetic assets, at their original paths and hashes, may ship."""
    if (src != dst or not is_reference_image(src)
            or entry.get("asset_kind") != "synthetic_reference"
            or entry.get("sha256") != hashlib.sha256(raw).hexdigest()):
        raise ValueError("reference image without reviewed digest: " + str(src))


def check_showcase_image(source: Path, src, dst, raw: bytes) -> None:
    """Admit a showcase image only when its set manifest records all passed gates."""
    def fail():
        raise ValueError("showcase image without passed gates: " + str(src))
    if not (in_showcase(src) and in_showcase(dst) and len(src.parts) == 4
            and src.parent == dst.parent):
        fail()
    try:
        manifest = json.loads(source.joinpath(*src.parent.parts, "manifest.json")
                              .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail()
    gates = manifest.get("gates") if isinstance(manifest, dict) else None
    if not (isinstance(gates, dict) and all(gates.get(g) is True for g in SHOWCASE_GATES)
            and isinstance(manifest.get("set_id"), str) and manifest["set_id"]
            and manifest.get("approved_by") == "owner"
            and isinstance(manifest.get("approved_on"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", manifest["approved_on"])
            and isinstance(manifest.get("images"), list)):
        fail()
    digest = hashlib.sha256(raw).hexdigest()
    listed = {}
    for item in manifest["images"]:
        if not (isinstance(item, dict) and isinstance(item.get("file"), str)
                and isinstance(item.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            fail()
        listed[item["file"]] = item["sha256"]
    if listed.get(src.name) != digest or listed.get(dst.name) != digest:
        fail()


def offline_document(text: str, destination: str, included: set) -> str:
    """Replace links to omitted local case assets with explicit text, never copy photos.

    Only rendered Markdown/HTML links are touched, not bare command/file paths.
    This runs on the export copy; the author's full local gallery stays intact.
    """
    def missing(url):
        target = urlsplit(url)
        if target.scheme or target.netloc or not target.path or target.path.startswith('/'):
            return False
        path = posixpath.normpath(posixpath.join(posixpath.dirname(destination), unquote(target.path)))
        return path.casefold() not in included
    def md(match):
        return match.group(1) + "（素材未包含于源码包）" if missing(match.group(2)) else match.group(0)
    text = re.sub(r"!?\[([^\]]*)\]\(([^)\s]+)\)", md, text)
    def anchor(match):
        return '<span>' + match.group(3) + '（素材未包含于源码包）</span>' if missing(match.group(2)) else match.group(0)
    text = re.sub(r"<a\b([^>]*?)href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", anchor, text, flags=re.S|re.I)
    def img(match):
        return '<span>图片未包含于源码包</span>' if missing(match.group(1)) else match.group(0)
    return re.sub(r"<img\b[^>]*src=[\"']([^\"']+)[\"'][^>]*>", img, text, flags=re.I)


def export(source: Path, output: Path, allowlist: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    entries = json.loads(allowlist.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError("invalid allowlist")
    style_rules = load_style_rules(source)
    prepared, seen, total, images, pairs = [], set(), 0, [], set()
    for entry in entries:
        src, dst = safe_path(entry["source"]), safe_path(entry["destination"])
        if set(src.parts) & FORBIDDEN or set(dst.parts) & FORBIDDEN:
            raise ValueError("private directory not permitted")
        if any(p.startswith(".env") for p in (*src.parts, *dst.parts)):
            raise ValueError("environment files not permitted")
        # Showcase images (and any .svg there) go through the manifest gate, not the text rules.
        # Both ends must be the same image type; a half-image entry gets no exemption.
        image_kinds = IMAGE_SUFFIXES | {".svg"}
        is_image = False
        reference_image = is_reference_image(src) or is_reference_image(dst)
        if reference_image:
            if src != dst:
                raise ValueError("reference image without reviewed digest: " + str(src))
            is_image = True
        if (in_showcase(src) or in_showcase(dst)) and any(
                p.suffix.lower() in image_kinds for p in (src, dst)):
            if not (src.suffix.lower() in image_kinds and dst.suffix.lower() in image_kinds
                    and src.suffix.lower() == dst.suffix.lower()):
                raise ValueError("showcase image without passed gates: " + str(src))
            is_image = True
        # casefold: case-insensitive filesystems treat case variants as the same list file
        if STYLE_KEYWORDS in (str(dst).casefold(), str(src).casefold()) and not (
                str(src) == str(dst) == STYLE_KEYWORDS):
            raise ValueError("style keyword list must export as itself")
        if not is_image and (src.suffix not in ALLOWED_SUFFIXES and src.name not in ALLOWED_EXTENSIONLESS
                or dst.suffix not in ALLOWED_SUFFIXES and dst.name not in ALLOWED_EXTENSIONLESS):
            raise ValueError("non-text asset not permitted")
        if str(dst).casefold() in seen or str(dst).casefold() == "public-export.json":
            raise ValueError("destination collision")
        seen.add(str(dst).casefold())
        file = source.joinpath(*src.parts)
        if any(source.joinpath(*src.parts[:i]).is_symlink() for i in range(1, len(src.parts) + 1)):
            raise ValueError("symbolic link not permitted")
        if not file.is_file() or source not in file.resolve().parents:
            raise ValueError("source file missing or outside source")
        # Preserve approved original PNGs; image hashes and gates still apply below.
        file_limit = (5 if is_image else 2) * 1024 * 1024
        if file.stat().st_size > file_limit:
            raise ValueError("source file too large")
        raw = file.read_bytes()
        if is_image:
            if reference_image:
                check_reference_image(entry, src, dst, raw)
            else:
                check_showcase_image(source, src, dst, raw)
            images.append(dst)
            total += len(raw)
            if total > LIMIT_BYTES:
                raise ValueError("export size exceeded")
            prepared.append((src, dst, raw, file.stat().st_mode))
            continue
        pairs.add((str(src), str(dst)))
        if str(dst) == "release/public-source-allowlist.json":
            # The exported tree re-exports itself, even when public documents
            # use different source names in the private development checkout.
            public_entries = [{**e, "source": e["destination"]}
                              for e in entries]
            raw = (json.dumps(public_entries, indent=2) + "\n").encode("utf-8")
        text = raw.decode("utf-8")
        if HOME_PATH.search(text) or SECRET.search(text):
            raise ValueError("private path or credential marker in " + str(src))
        if not (str(src) == str(dst) == STYLE_KEYWORDS):  # exempt only the list itself, never a file renamed onto it
            if any(r.search(text) for r in style_rules):
                raise ValueError("costume keyword in " + str(src))
        total += len(raw)
        if total > LIMIT_BYTES:
            raise ValueError("export size exceeded")
        prepared.append((src, dst, raw, file.stat().st_mode))
    required = {"readme.md", "license", "skills/shy-cameo/skill.md",
                "scripts/export_public_source.py", "release/public-source-allowlist.json",
                "scripts/build_v1_release.py", "release/plugin.json",
                "release/runtime-allowlist.json", "release/style-keywords.json"}
    if not required <= seen:
        raise ValueError("required public source files missing")
    for image in images:
        if is_reference_image(image):
            continue
        manifest = str(image.parent / "manifest.json")
        if (manifest, manifest) not in pairs:
            raise ValueError("showcase image without passed gates: " + str(image))
    # Verify build dependencies in the exported tree, not in the private checkout.
    exported = {str(dst): raw for _, dst, raw, _ in prepared}
    runtime_entries = json.loads(exported["release/runtime-allowlist.json"])
    if not isinstance(runtime_entries, list) or not 1 <= len(runtime_entries) <= 500:
        raise ValueError("invalid runtime allowlist")
    for entry in runtime_entries:
        path = str(safe_path(entry["source"]))
        if path not in exported:
            raise ValueError("runtime build source missing from export: " + path)
    plugin = json.loads(exported["release/plugin.json"])
    version = plugin.get("version") if isinstance(plugin, dict) else None
    if (not isinstance(plugin, dict) or plugin.get("name") != "shy-cameo" or not isinstance(version, str)
            or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version)):
        raise ValueError("invalid plugin version")
    # Source archives exclude private image assets; avoid dangling
    # gallery links while preserving local originals and the export allowlist.
    prepared = [(src, dst, offline_document(raw.decode("utf-8"), str(dst), seen).encode("utf-8")
                 if dst.suffix in (".md", ".html") and dst not in images else raw, mode)
                for src, dst, raw, mode in prepared]
    total = sum(len(raw) for _, _, raw, _ in prepared)
    if total > LIMIT_BYTES:
        raise ValueError("export size exceeded")
    # Validate all entries first, never overwrite an existing export.
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for src, dst, raw, mode in prepared:
        dest = output.joinpath(*dst.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        if mode & 0o111:
            dest.chmod(0o755)
        rows.append({"source": str(src), "path": str(dst), "bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"version": version, "status": "candidate", "git_history_included": False,
                "allowlist_normalized_to_public_paths": True,
                "images_included": bool(images), "files": rows}
    (output / "PUBLIC-EXPORT.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"status": "candidate", "source_directory": str(output), "files": len(rows), "bytes": total}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "output", "allowlist"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = export(args.source, args.output, args.allowlist)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
