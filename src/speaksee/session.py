from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    audio_pcm16: bytearray = field(default_factory=bytearray)
    sample_rate: int = 16000
    recording: bool = False

    style: str = "none"  # "none" | "realistic" | "abstract"
    last_prompt: Optional[str] = None
    last_negative_prompt: str = ""

    last_image_id: Optional[str] = None

    transcription_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    generation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    generation_token: int = 0

    def bump_generation_token(self) -> int:
        self.generation_token += 1
        return self.generation_token

