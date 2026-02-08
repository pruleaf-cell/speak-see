from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Config


@dataclass(frozen=True)
class SttResult:
    text: str


class SpeechToText:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._model = None
        self._model_device = None

    def _select_device(self) -> str:
        # faster-whisper supports cpu and cuda.
        pref = self._cfg.device_preference
        if pref == "cuda":
            try:
                import torch

                if torch.cuda.is_available():
                    return "cuda"
            except Exception:
                return "cpu"
        return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        from faster_whisper import WhisperModel  # heavy import, keep lazy

        device = self._select_device()
        compute_type = "float16" if device == "cuda" else "int8"

        download_root = Path(self._cfg.hf_home) / "whisper"
        download_root.mkdir(parents=True, exist_ok=True)

        # Prefer local-only first; fall back to auto-download if missing.
        try:
            self._model = WhisperModel(
                self._cfg.whisper_model,
                device=device,
                compute_type=compute_type,
                download_root=str(download_root),
                local_files_only=True,
            )
        except Exception:
            self._model = WhisperModel(
                self._cfg.whisper_model,
                device=device,
                compute_type=compute_type,
                download_root=str(download_root),
                local_files_only=False,
            )
        self._model_device = device

    @staticmethod
    def _pcm16_to_float32(pcm16: bytes) -> np.ndarray:
        if not pcm16:
            return np.zeros((0,), dtype=np.float32)
        a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
        return a / 32768.0

    def transcribe_final(self, pcm16: bytes, sample_rate: int) -> SttResult:
        self._ensure_model()
        audio = self._pcm16_to_float32(pcm16)
        if audio.size == 0:
            return SttResult(text="")

        # NOTE: audio from the client is expected to already be 16kHz mono PCM16.
        segments, _info = self._model.transcribe(  # type: ignore[operator]
            audio,
            beam_size=5,
            best_of=5,
            vad_filter=True,
        )
        text = "".join(seg.text for seg in segments).strip()
        return SttResult(text=text)

    def transcribe_partial(self, pcm16: bytes, sample_rate: int) -> SttResult:
        """
        Cheap partial transcript for live preview. Uses a smaller decode.
        """
        self._ensure_model()
        audio = self._pcm16_to_float32(pcm16)
        if audio.size == 0:
            return SttResult(text="")

        segments, _info = self._model.transcribe(  # type: ignore[operator]
            audio,
            beam_size=1,
            best_of=1,
            vad_filter=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        return SttResult(text=text)

    @property
    def device(self) -> str:
        self._ensure_model()
        return str(self._model_device or "cpu")

