import io
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from speaksee.config import Config
from speaksee.server import create_app


def _cfg(tmp_path: Path) -> Config:
    data_dir = tmp_path / "data"
    gallery_dir = data_dir / "gallery"
    saved_dir = data_dir / "saved"
    hf_home = data_dir / "hf"
    gallery_dir.mkdir(parents=True, exist_ok=True)
    saved_dir.mkdir(parents=True, exist_ok=True)
    hf_home.mkdir(parents=True, exist_ok=True)
    return Config(
        root_dir=tmp_path,
        host="127.0.0.1",
        port=7860,
        data_dir=data_dir,
        gallery_dir=gallery_dir,
        saved_dir=saved_dir,
        hf_home=hf_home,
        sd_model="hf-internal-testing/tiny-stable-diffusion-pipe",
        whisper_model="Systran/faster-whisper-base",
        steps=1,
        width=64,
        height=64,
        device_preference="cpu",
    )


def _assert_not_all_black_png(png_bytes: bytes) -> None:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    extrema = img.getextrema()  # [(min,max), (min,max), (min,max)]
    assert extrema is not None
    assert any(mx > 0 for _mn, mx in extrema), f"image looks all-black: extrema={extrema}"


def test_smoke_ws_generate_and_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("SPEAKSEE_OFFLINE", "").strip() in ("1", "true", "yes", "on"):
        pytest.skip("SPEAKSEE_OFFLINE set")

    cfg = _cfg(tmp_path)
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    app = create_app(cfg)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "ui_version": "1", "client": "pytest"})

        ws.send_json({"type": "generate", "prompt": "a cat sitting on a chair"})

        result = None
        for _ in range(200):
            msg = ws.receive_json()
            if msg.get("type") == "error":
                raise AssertionError(msg)
            if msg.get("type") == "gen_result":
                result = msg
                break
        assert result is not None, "did not receive gen_result"

        img_resp = client.get(result["url"])
        assert img_resp.status_code == 200
        _assert_not_all_black_png(img_resp.content)

        ws.send_json({"type": "action", "name": "save_image"})
        saved = None
        for _ in range(50):
            msg = ws.receive_json()
            if msg.get("type") == "saved":
                saved = msg
                break
            if msg.get("type") == "error":
                raise AssertionError(msg)
        assert saved is not None, "did not receive saved"
        assert (cfg.saved_dir / f"{saved['id']}.png").exists()
