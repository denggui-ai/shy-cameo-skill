import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from coshoot.cards import CardError, schema_errors
from coshoot.library import cache_path, fetch_asset, promote_card, resolve_sheet, sha256_bytes

FIX = Path(__file__).parent / "fixtures" / "cards"
BASE = "https://github.com/denggui-ai/classic-coshoot/releases/download/library-v1"

DATA = b"fake-sheet-bytes"


def asset(url="https://example.invalid/a.png", data=DATA):
    return {"url": url, "sha256": sha256_bytes(data), "bytes": len(data)}


def opener_for(data, calls):
    @contextmanager
    def _open(url, timeout):
        calls.append(url)
        yield io.BytesIO(data)
    return _open


def test_fetch_downloads_verifies_and_caches(tmp_path):
    calls = []
    a = asset()
    path = fetch_asset(a, tmp_path, opener_for(DATA, calls))
    assert path.read_bytes() == DATA and path == cache_path(a, tmp_path)
    fetch_asset(a, tmp_path, opener_for(DATA, calls))
    assert len(calls) == 1  # second call is a cache hit


def test_fetch_rejects_tampered_download(tmp_path):
    with pytest.raises(CardError) as exc:
        fetch_asset(asset(), tmp_path, opener_for(b"tampered", []))
    assert exc.value.code == "asset_integrity"
    assert not cache_path(asset(), tmp_path).exists()


def test_resolve_remote_requires_prior_fetch(tmp_path):
    with pytest.raises(CardError) as exc:
        resolve_sheet(asset(), tmp_path / "cache", tmp_path)
    assert exc.value.code == "asset_not_fetched"


def test_resolve_workspace_asset_and_reject_escape(tmp_path):
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "head.png").write_bytes(DATA)
    ok = resolve_sheet(asset("characters/head.png"), tmp_path / "cache", tmp_path)
    assert ok.name == "head.png"
    with pytest.raises(CardError) as exc:
        resolve_sheet(asset("../outside.png"), tmp_path / "cache", tmp_path)
    assert exc.value.code == "asset_outside_workspace"


def test_resolve_detects_modified_workspace_asset(tmp_path):
    (tmp_path / "h.png").write_bytes(b"changed")
    with pytest.raises(CardError) as exc:
        resolve_sheet(asset("h.png"), tmp_path / "cache", tmp_path)
    assert exc.value.code == "asset_integrity"


def test_fetch_reads_at_most_expected_bytes_plus_one(tmp_path):
    sizes = []

    class Resp(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            return super().read(size)

    @contextmanager
    def _open(url, timeout):
        yield Resp(DATA + b"x" * 1000)

    with pytest.raises(CardError) as exc:
        fetch_asset(asset(), tmp_path, _open)
    assert exc.value.code == "asset_integrity" and sizes == [len(DATA) + 1]


def confirmed_card(ws):
    card = json.loads((FIX / "wukong.json").read_text(encoding="utf-8"))
    card["status"] = "temp_confirmed"
    for variant in card["variants"]:
        for kind in ("head", "body"):
            rel = f"characters/xiyou-wukong/{variant['variant_id']}-{kind}.png"
            data = f"{variant['variant_id']}-{kind}".encode()
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_bytes(data)
            variant["sheets"][kind] = {"url": rel, "sha256": sha256_bytes(data), "bytes": len(data)}
    return card


def test_promote_card_maps_release_urls_and_stages_bytes(tmp_path):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    gold, uploads = promote_card(confirmed_card(ws), BASE, ws, stage)
    assert gold["status"] == "gold" and schema_errors(gold, "character") == []
    head = gold["variants"][0]["sheets"]["head"]
    assert head == {"url": BASE + "/xiyou-wukong-mhw-head.png", "sha256": sha256_bytes(b"mhw-head"), "bytes": 8}
    assert (stage / "xiyou-wukong-mhw-head.png").read_bytes() == b"mhw-head"
    assert sorted(u["name"] for u in uploads) == [
        "xiyou-wukong-mhw-body.png", "xiyou-wukong-mhw-head.png",
        "xiyou-wukong-qujing-body.png", "xiyou-wukong-qujing-head.png"]


@pytest.mark.parametrize("mutate,code", [
    (lambda c: c.update(status="temp_draft"), "character_not_confirmed"),
])
def test_promote_card_refuses_before_staging(tmp_path, mutate, code):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    card = confirmed_card(ws)
    mutate(card)
    with pytest.raises(CardError) as exc:
        promote_card(card, BASE, ws, stage)
    assert exc.value.code == code and not stage.exists()


def test_promote_card_accepts_head_only_variant(tmp_path):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    card = confirmed_card(ws)
    for variant in card["variants"]:
        variant["sheets"].pop("body")
    gold, uploads = promote_card(card, BASE, ws, stage)
    for variant in gold["variants"]:
        assert set(variant["sheets"]) == {"head"}
        assert variant["sheets"]["head"]["url"].startswith(BASE + "/")
    assert sorted(u["name"] for u in uploads) == ["xiyou-wukong-mhw-head.png", "xiyou-wukong-qujing-head.png"]


def test_promote_card_accepts_sheetless_variant(tmp_path):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    card = confirmed_card(ws)
    card["variants"][1].pop("sheets")
    gold, uploads = promote_card(card, BASE, ws, stage)
    assert "sheets" not in gold["variants"][1] and len(uploads) == 2


def test_promote_card_requires_https_base(tmp_path):
    with pytest.raises(CardError) as exc:
        promote_card(confirmed_card(tmp_path / "ws"), "http://example.invalid/x", tmp_path / "ws", tmp_path / "s")
    assert exc.value.code == "bad_release_base"


def test_promote_card_refuses_duplicate_variant_ids(tmp_path):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    card = confirmed_card(ws)
    card["variants"][1]["variant_id"] = card["variants"][0]["variant_id"]
    with pytest.raises(CardError) as exc:
        promote_card(card, BASE, ws, stage)
    assert exc.value.code == "duplicate_variant" and not stage.exists()


def test_promote_card_does_not_require_optional_lookalike_vote(tmp_path):
    ws, stage = tmp_path / "ws", tmp_path / "stage"
    card = confirmed_card(ws)
    card["variants"][0]["lookalike_check"]["status"] = "pending"
    gold, uploads = promote_card(card, BASE, ws, stage)
    assert gold["status"] == "gold" and uploads
    assert gold["variants"][0]["lookalike_check"]["status"] == "pending"
