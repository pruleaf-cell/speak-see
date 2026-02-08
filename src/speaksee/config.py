from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip()


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    root_dir: Path

    host: str
    port: int

    data_dir: Path
    gallery_dir: Path
    saved_dir: Path
    hf_home: Path

    sd_model: str
    whisper_model: str

    steps: int
    width: int
    height: int

    device_preference: str  # "cpu" | "mps" | "cuda" | "auto"

    stt_partial_interval_s: float = 0.8
    stt_partial_window_s: float = 8.0

    autogen_delay_s: float = 1.2

    realistic_prompt_suffix: str = (
        "photorealistic, natural lighting, high detail, 35mm, realistic"
    )
    realistic_negative: str = "cartoon, anime, illustration, lowres"

    abstract_prompt_suffix: str = "abstract, painterly, expressive, textured, modern art"
    abstract_negative: str = "photorealistic, realistic"


def load_config() -> Config:
    root_dir = Path(__file__).resolve().parents[2]

    host = _env_str("SPEAKSEE_HOST", "127.0.0.1")
    port = _env_int("SPEAKSEE_PORT", 7860)

    data_dir = root_dir / "data"
    gallery_dir = data_dir / "gallery"
    saved_dir = data_dir / "saved"
    hf_home = Path(_env_str("HF_HOME", str(data_dir / "hf")))

    sd_model = _env_str("SPEAKSEE_SD_MODEL", "stabilityai/sd-turbo")
    whisper_model = _env_str("SPEAKSEE_WHISPER_MODEL", "Systran/faster-whisper-base")

    steps = _env_int("SPEAKSEE_STEPS", 4)
    width = _env_int("SPEAKSEE_WIDTH", 512)
    height = _env_int("SPEAKSEE_HEIGHT", 512)

    device_preference = _env_str("SPEAKSEE_DEVICE", "auto").lower()
    if device_preference not in ("auto", "cpu", "mps", "cuda"):
        device_preference = "auto"

    # Ensure directories exist (no prompts).
    data_dir.mkdir(parents=True, exist_ok=True)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    saved_dir.mkdir(parents=True, exist_ok=True)
    hf_home.mkdir(parents=True, exist_ok=True)

    return Config(
        root_dir=root_dir,
        host=host,
        port=port,
        data_dir=data_dir,
        gallery_dir=gallery_dir,
        saved_dir=saved_dir,
        hf_home=hf_home,
        sd_model=sd_model,
        whisper_model=whisper_model,
        steps=steps,
        width=width,
        height=height,
        device_preference=device_preference,
    )

