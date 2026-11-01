"""Tiny PNG/JPEG header readers (stdlib only)."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import List, Optional, Tuple

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_chunk_types(data: bytes) -> List[str]:
    if not data.startswith(PNG_SIG):
        return []
    types: List[str] = []
    pos = len(PNG_SIG)
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        types.append(ctype.decode("latin-1"))
        pos += 12 + length
        if ctype == b"IEND":
            break
    return types


def has_c2pa(path: Path) -> bool:
    return "caBX" in png_chunk_types(Path(path).read_bytes())


def image_size(path: Path) -> Optional[Tuple[int, int]]:
    data = Path(path).read_bytes()
    if data.startswith(PNG_SIG) and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return (width, height)
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2) and pos + 9 <= len(data):
                height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
                return (width, height)
            pos += 2 + length
    return None


def png_decode_error(path: Path) -> Optional[str]:
    """Validate PNG pixel stream without rewriting the file or requiring OpenCV/Pillow.

    Non-PNGs are handled by their existing format path. Adam7 and all PNG colour
    types are supported. A validation memory bound prevents hostile headers.
    """
    import zlib
    data = Path(path).read_bytes()
    if not data.startswith(PNG_SIG):
        return None
    try:
        pos, parts, kinds = 8, [], []
        header = None
        palette = None
        while pos < len(data):
            length, kind = struct.unpack('>I4s', data[pos:pos+8])
            end = pos + 12 + length
            if end > len(data) or zlib.crc32(data[pos+4:end-4]) & 0xffffffff != struct.unpack('>I', data[end-4:end])[0]:
                raise ValueError('invalid PNG chunk')
            payload = data[pos+8:end-4]
            kinds.append(kind)
            if kind == b'IHDR':
                if header is not None or length != 13:
                    raise ValueError('invalid IHDR')
                header = struct.unpack('>IIBBBBB', payload)
            if kind == b'PLTE':
                if palette is not None or b'IDAT' in kinds or not length or length % 3 or length > 768:
                    raise ValueError('invalid PNG palette')
                palette = payload
            if kind == b'IDAT':
                parts.append(payload)
            pos = end
        if not header or kinds[0] != b'IHDR' or kinds[-1] != b'IEND' or not parts:
            raise ValueError('incomplete PNG')
        w, h, depth, color, comp, filt, interlace = header
        channels = {0:1, 2:3, 3:1, 4:2, 6:4}.get(color)
        allowed = {0:(1,2,4,8,16), 2:(8,16), 3:(1,2,4,8), 4:(8,16), 6:(8,16)}
        if not w or not h or not channels or depth not in allowed[color] or comp or filt or interlace not in (0,1):
            raise ValueError('invalid PNG header')
        if color == 3 and (palette is None or len(palette)//3 > 2**depth):
            raise ValueError('missing or invalid indexed PNG palette')
        passes = [(0,0,1,1)] if not interlace else [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
        rows = []
        for x,y,dx,dy in passes:
            pw, ph = max(0,(w-x+dx-1)//dx), max(0,(h-y+dy-1)//dy)
            if pw and ph:
                rows.append((((pw*channels*depth+7)//8)+1, ph))
        expected = sum(n*count for n,count in rows)
        if expected > 256*1024*1024:
            raise ValueError('PNG exceeds local decode validation memory budget')
        dec = zlib.decompressobj()
        pixels = dec.decompress(b''.join(parts), expected+1)
        if len(pixels) != expected or not dec.eof or dec.unused_data or dec.unconsumed_tail:
            raise ValueError('invalid PNG pixel stream')
        offset = 0
        for n,count in rows:
            for _ in range(count):
                if pixels[offset] > 4:
                    raise ValueError('invalid PNG filter')
                offset += n
        return None
    except (ValueError, KeyError, IndexError, struct.error, zlib.error) as exc:
        return str(exc)
