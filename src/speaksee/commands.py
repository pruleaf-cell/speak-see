from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional


Style = Literal["none", "realistic", "abstract"]
CommandName = Literal["regenerate", "save_image", "set_style"]


@dataclass(frozen=True)
class ParsedVoiceCommand:
    name: Literal["regenerate", "more_realistic", "more_abstract", "save_image"]


_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    t = text.strip().lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def parse_voice_command(text: str) -> Optional[ParsedVoiceCommand]:
    """
    Interpret voice commands only when spoken as a standalone command (plus optional polite words),
    so regular prompts containing these phrases won't accidentally trigger actions.
    """
    n = normalize_text(text)
    if not n:
        return None

    # Strip common filler/polite words.
    n = re.sub(r"^(please|hey|ok|okay)\s+", "", n).strip()
    n = re.sub(r"\s+(please|thanks|thank you)$", "", n).strip()

    if re.fullmatch(r"regenerate", n):
        return ParsedVoiceCommand("regenerate")
    if re.fullmatch(r"more realistic", n):
        return ParsedVoiceCommand("more_realistic")
    if re.fullmatch(r"more abstract", n):
        return ParsedVoiceCommand("more_abstract")
    if re.fullmatch(r"save (the )?image", n):
        return ParsedVoiceCommand("save_image")
    return None


def style_suffix(style: Style) -> str:
    if style == "realistic":
        return "realistic"
    if style == "abstract":
        return "abstract"
    return "none"
