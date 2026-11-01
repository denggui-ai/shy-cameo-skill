import json

import pytest

from coshoot.cards import CardError
from coshoot.label import deliver
from coshoot.library import sha256_file
from coshoot.png import has_c2pa, image_size, png_chunk_types

REQ = {"run_id": "20261010-120000-abcdef", "sha256": "0" * 64}
CONSENT = {"subject_confirmed": True, "adult_confirmed": True,
           "self_or_consented": True, "at": "2026-10-10T12:00:00"}
AUDIT = {"status": "unverified", "reason": "test"}


def test_png_helpers(tmp_path, png_factory):
    p = tmp_path / "a.png"
    p.write_bytes(png_factory(10, 6, extra=[(b"caBX", b"c2pa-manifest")]))
    assert png_chunk_types(p.read_bytes()) == ["IHDR", "caBX", "IDAT", "IEND"]
    assert has_c2pa(p) and image_size(p) == (10, 6)


def test_jpeg_size_is_read(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    p = tmp_path / "a.jpg"
    PIL.new("RGB", (32, 20)).save(p, format="JPEG")
    assert image_size(p) == (32, 20)


def test_deliver_copies_bytes_exactly_and_keeps_c2pa(tmp_path, png_factory):
    src = tmp_path / "exec-1.png"
    src.write_bytes(png_factory(extra=[(b"caBX", b"c2pa-manifest")]))
    side = deliver(src, tmp_path / "run", REQ, CONSENT, AUDIT)
    out = tmp_path / "run" / "image.png"
    assert sha256_file(out) == sha256_file(src) == side["original_sha256"]
    assert side["c2pa_present"] is True and side["badge_path"] is None
    assert side["verdict"] == "pending"
    assert json.loads((tmp_path / "run" / "sidecar.json").read_text(encoding="utf-8")) == side


def test_deliver_requires_full_consent(tmp_path, png_factory):
    src = tmp_path / "x.png"
    src.write_bytes(png_factory())
    with pytest.raises(CardError) as exc:
        deliver(src, tmp_path / "run", REQ, dict(CONSENT, adult_confirmed=False), AUDIT)
    assert exc.value.code == "blocked_consent"


def test_badge_is_a_separate_derivative(tmp_path, png_factory):
    pytest.importorskip("PIL")
    src = tmp_path / "x.png"
    src.write_bytes(png_factory(64, 64, extra=[(b"caBX", b"m")]))
    side = deliver(src, tmp_path / "run", REQ, CONSENT, AUDIT, badge=True)
    assert side["badge_path"].endswith("image-badge.png")
    assert sha256_file(tmp_path / "run" / "image.png") == sha256_file(src)
    assert not has_c2pa(tmp_path / "run" / "image-badge.png")


def test_second_delivery_on_same_run_is_refused(tmp_path, png_factory):
    src = tmp_path / "exec-1.png"
    src.write_bytes(png_factory())
    deliver(src, tmp_path / "run", REQ, CONSENT, AUDIT)
    sidecar = tmp_path / "run" / "sidecar.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["verdict"] = "accepted"
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    before = sidecar.read_bytes()
    other = tmp_path / "exec-2.png"
    other.write_bytes(png_factory(12, 12))
    with pytest.raises(CardError) as exc:
        deliver(other, tmp_path / "run", REQ, CONSENT, AUDIT)
    assert exc.value.code == "already_delivered"
    assert sidecar.read_bytes() == before
    assert (tmp_path / "run" / "image.png").read_bytes() == src.read_bytes()
