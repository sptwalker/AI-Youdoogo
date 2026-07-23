"""Pure scoring and comparison policies."""

from __future__ import annotations

import re

_SCORE_RE = re.compile(r"([1-5])")


def judge_score(judge_output: str) -> int:
    lines = (judge_output or "").strip().splitlines()
    first = lines[0] if lines else ""
    match = _SCORE_RE.search(first)
    if match:
        return int(match.group(1))
    fallback = _SCORE_RE.search(judge_output or "")
    return int(fallback.group(1)) if fallback else 3


def average_score(scores: tuple[int, ...]) -> float:
    return round(sum(scores) / len(scores), 3) if scores else 0.0
