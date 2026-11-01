"""Actor-name deny list: real actor names must never reach an image prompt."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import SKILL_ROOT, load_json

DEFAULT_NAMES_PATH = SKILL_ROOT / "library" / "policy" / "actor-names.json"

# Greek and Cyrillic letters that look like Latin ones; NFKC leaves them alone (P1 ruling R9 backlog).
CONFUSABLES = str.maketrans({
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Υ": "Y", "Χ": "X", "α": "a", "ι": "i", "κ": "k", "ν": "v",
    "ο": "o", "ρ": "p",
    "Ѕ": "S", "І": "I", "Ј": "J", "А": "A", "В": "B", "Е": "E",
    "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "Х": "X", "а": "a", "е": "e", "о": "o", "р": "p",
    "с": "c", "у": "y", "х": "x", "ѕ": "s", "і": "i", "ј": "j",
    "һ": "h", "ԝ": "w", "ԁ": "d", "ԛ": "q",
})


# Common words that start with a name's last character or end with its first one. A Chinese hit
# glued to such a word is ordinary text, e.g. 李靖飞行器 / 孙彦军队 / 汪粤语 (P1 ruling R11).
CJK_SPLIT_WORDS = frozenset({
    "飞行", "飞身", "飞来", "飞去", "飞到", "飞上", "飞下", "飞过", "飞起", "飞出", "飞向", "飞奔",
    "飞快", "飞速", "飞舞", "飞落", "飛行", "飛身", "飛來", "飛去", "飛到", "飛上", "飛下", "飛過",
    "飛起", "飛出", "飛向", "飛奔", "飛快", "飛速", "飛舞", "飛落",
    "军队", "军营", "军装", "军中", "军旗", "军阵", "军帐", "军令", "軍隊", "軍營", "軍裝", "軍中",
    "軍旗", "軍陣", "軍帳", "軍令",
    "粤语", "粤剧", "粤菜", "粤曲", "粵語", "粵劇", "粵菜", "粵曲",
})


@dataclass(frozen=True)
class NameEntry:
    name: str
    aliases: Tuple[str, ...] = ()
    maps_to: Optional[Dict[str, str]] = field(default=None, compare=False, hash=False)

    def terms(self) -> Tuple[str, ...]:
        return (self.name,) + tuple(self.aliases)


@dataclass(frozen=True)
class NameHit:
    matched: str
    entry: NameEntry


def load_names(path: Path = DEFAULT_NAMES_PATH) -> List[NameEntry]:
    data = load_json(path)
    return [NameEntry(e["name"], tuple(e.get("aliases", [])), e.get("maps_to"))
            for e in data["entries"]]


def _compact(value: str) -> str:
    """NFKC-normalise, then drop whitespace and every Unicode format (Cf) character."""
    value = unicodedata.normalize("NFKC", value)
    return "".join(ch for ch in value
                   if not ch.isspace() and unicodedata.category(ch) != "Cf")


def _spaced(value: str) -> str:
    """NFKC-normalise, drop Cf characters, and collapse every whitespace run to one ASCII space."""
    value = unicodedata.normalize("NFKC", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", value)


def _bounded_match(term: str, folded: str, original: str) -> bool:
    """Find term in folded text; reject if an ASCII letter touches it in the unfolded original.

    The fold is 1:1 per character, so indices line up and a glued look-alike cannot break the boundary.
    """
    for m in re.finditer(re.escape(term), folded, re.IGNORECASE):
        before = original[m.start() - 1] if m.start() else ""
        after = original[m.end()] if m.end() < len(original) else ""
        if not (before.isascii() and before.isalpha()) and not (after.isascii() and after.isalpha()):
            return True
    return False


def _matches(term: str, text: str) -> bool:
    term = unicodedata.normalize("NFKC", term)
    text = unicodedata.normalize("NFKC", text)
    if term.isascii():
        compact_text = _compact(text)
        spaced_text = _spaced(text)
        return (_bounded_match(term, text.translate(CONFUSABLES), text)
                or _bounded_match(_spaced(term), spaced_text.translate(CONFUSABLES), spaced_text)
                or _bounded_match(_compact(term), compact_text.translate(CONFUSABLES), compact_text))
    return _cjk_match(_compact(term), text)


def _cjk_match(term: str, text: str) -> bool:
    """Substring match on the compact text, skipping hits whose edge character forms a common word
    with a neighbour that is truly adjacent (no whitespace between them in the original text)."""
    chars, gap_before = [], []
    gap = False
    for ch in text:
        if ch.isspace():
            gap = True
        elif unicodedata.category(ch) != "Cf":
            chars.append(ch)
            gap_before.append(gap)
            gap = False
    compact = "".join(chars)

    def split_word(i: int) -> bool:  # the pair compact[i-1:i+1] is one glued common word
        return 0 < i < len(compact) and not gap_before[i] and compact[i - 1:i + 1] in CJK_SPLIT_WORDS

    start = compact.find(term)
    while start != -1:
        end = start + len(term)
        if not split_word(end) and not split_word(start):
            return True
        start = compact.find(term, start + 1)
    return False


def scan(text: str, entries: Sequence[NameEntry]) -> List[NameHit]:
    hits: List[NameHit] = []
    for entry in entries:
        for term in entry.terms():
            if term and _matches(term, text):
                hits.append(NameHit(term, entry))
                break
    return hits


def classify(text: str, entries: Sequence[NameEntry]) -> Dict[str, list]:
    """Split hits into mappable (-> character + version label) and blocked."""
    mappable, blocked = [], []
    for hit in scan(text, entries):
        if hit.entry.maps_to:
            mappable.append({"matched": hit.matched, **hit.entry.maps_to})
        else:
            blocked.append(hit.matched)
    return {"mappable": mappable, "blocked": blocked}
