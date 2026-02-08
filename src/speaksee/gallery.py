from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from .config import Config


def _now_ts() -> tuple[str, str]:
    # ISO-ish for metadata and filesystem-safe ID for filenames.
    now = datetime.now().astimezone().replace(microsecond=0)
    ts = now.isoformat()
    fid = now.strftime("%Y-%m-%dT%H-%M-%S")
    return ts, fid


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def save_generated_image(
    cfg: Config,
    image: Image.Image,
    *,
    prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int,
    style: str,
    model_id: str,
    device: str,
) -> dict[str, Any]:
    ts, fid = _now_ts()
    image_id = f"{fid}_seed{seed}"

    png_name = f"{image_id}.png"
    json_name = f"{image_id}.json"

    png_path = cfg.gallery_dir / png_name
    json_path = cfg.gallery_dir / json_name

    image.save(png_path, format="PNG")
    meta = {
        "id": image_id,
        "ts": ts,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "steps": steps,
        "style": style,
        "model_id": model_id,
        "device": device,
        "file": png_name,
    }
    _write_json(json_path, meta)
    return meta


def list_gallery(cfg: Config, limit: int = 200) -> list[dict[str, str]]:
    items: list[tuple[str, Path]] = []
    for p in cfg.gallery_dir.glob("*.png"):
        items.append((p.name, p))
    items.sort(key=lambda t: t[0], reverse=True)

    out: list[dict[str, str]] = []
    for name, p in items[:limit]:
        image_id = name[:-4]
        meta_path = p.with_suffix(".json")
        ts = ""
        if meta_path.exists():
            try:
                ts = json.loads(meta_path.read_text(encoding="utf-8")).get("ts", "")
            except Exception:
                ts = ""
        out.append({"id": image_id, "url": f"/images/{name}", "ts": ts})
    return out


def copy_to_saved(cfg: Config, image_id: str) -> Path:
    src = cfg.gallery_dir / f"{image_id}.png"
    if not src.exists():
        raise FileNotFoundError(f"Image not found: {src}")
    dst = cfg.saved_dir / f"{image_id}.png"
    shutil.copyfile(src, dst)
    return dst

