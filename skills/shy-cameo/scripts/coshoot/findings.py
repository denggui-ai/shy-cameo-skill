"""Shared finding type for checks (photo, frame, preflight)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List, Sequence

LEVELS = ("block", "confirm", "warn", "info")


@dataclass
class Finding:
    level: str  # one of LEVELS
    code: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def worst_level(levels: Sequence[str]) -> str:
    for level in LEVELS:
        if level in levels:
            return level
    return "ok"


def worst(findings: List[Finding]) -> str:
    return worst_level([f.level for f in findings])
