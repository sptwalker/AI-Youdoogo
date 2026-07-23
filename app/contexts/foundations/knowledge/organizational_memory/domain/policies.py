"""Pure preparation policy for conversation distillation."""

from __future__ import annotations

MAX_TRANSCRIPT_CHARS = 8000


def build_distillation_input(transcript: str) -> str:
    return f"请提炼以下对话记录：\n\n{transcript[:MAX_TRANSCRIPT_CHARS]}"
