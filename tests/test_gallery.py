from pathlib import Path

from PIL import Image

from speaksee.config import Config
from speaksee.gallery import copy_to_saved, list_gallery, save_generated_image


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
        sd_model="stabilityai/sd-turbo",
        whisper_model="Systran/faster-whisper-base",
        steps=4,
        width=512,
        height=512,
        device_preference="cpu",
    )


def test_gallery_save_and_list(tmp_path: Path):
    cfg = _cfg(tmp_path)
    img = Image.new("RGB", (64, 64), color=(255, 0, 0))
    meta = save_generated_image(
        cfg,
        img,
        prompt="test prompt",
        negative_prompt="",
        seed=123,
        steps=4,
        style="none",
        model_id=cfg.sd_model,
        device="cpu",
    )
    assert (cfg.gallery_dir / f"{meta['id']}.png").exists()
    assert (cfg.gallery_dir / f"{meta['id']}.json").exists()

    items = list_gallery(cfg)
    assert items
    assert items[0]["id"] == meta["id"]
    assert items[0]["url"].endswith(f"{meta['id']}.png")


def test_copy_to_saved(tmp_path: Path):
    cfg = _cfg(tmp_path)
    img = Image.new("RGB", (32, 32), color=(0, 255, 0))
    meta = save_generated_image(
        cfg,
        img,
        prompt="x",
        negative_prompt="",
        seed=1,
        steps=1,
        style="none",
        model_id=cfg.sd_model,
        device="cpu",
    )
    dst = copy_to_saved(cfg, meta["id"])
    assert dst.exists()
    assert dst.name == f"{meta['id']}.png"

