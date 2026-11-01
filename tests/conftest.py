import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "shy-cameo"
sys.path.insert(0, str(SKILL / "scripts"))

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype, data):
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def make_png(w=8, h=8, extra=()):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    return (PNG_SIG + _chunk(b"IHDR", ihdr) + b"".join(_chunk(t, d) for t, d in extra)
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


@pytest.fixture
def png_factory():
    return make_png


@pytest.fixture
def skill_root():
    return SKILL
