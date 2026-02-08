from __future__ import annotations

import math
import random
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image

from .config import Config


ProgressCb = Callable[[int, int], None]


@dataclass(frozen=True)
class ImageGenResult:
    image: Image.Image
    seed: int
    device: str


class ImageGenerator:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._pipe = None
        self._device = None
        self._dtype = None

    def _select_device(self) -> str:
        pref = self._cfg.device_preference
        try:
            import torch
        except Exception:
            return "cpu"

        if pref == "cpu":
            return "cpu"
        if pref == "cuda":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if pref == "mps":
            return "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"

        # auto
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _ensure_pipe(self) -> None:
        if self._pipe is not None:
            return

        import torch
        from diffusers import AutoPipelineForText2Image

        device = self._select_device()
        # Use float16 on CUDA/MPS for performance. On MPS we avoid fp16 *variants* (see attempts below)
        # because some fp16 variant weights can yield all-black images.
        dtype = torch.float16 if device in ("cuda", "mps") else torch.float32

        # Prefer local-only first; fall back to download. Cache dir is HF_HOME (already set by run script).
        model_id = self._cfg.sd_model
        cache_dir = str(self._cfg.hf_home)

        last_err: Exception | None = None

        attempts: list[dict[str, object]] = []
        # 1) Local-only, fp16 variant (if applicable)
        attempts.append({"local_files_only": True, "use_variant_fp16": device == "cuda"})
        # 2) Allow download, fp16 variant (if applicable)
        attempts.append({"local_files_only": False, "use_variant_fp16": device == "cuda"})
        # 3) Allow download, no variant (more compatible)
        attempts.append({"local_files_only": False, "use_variant_fp16": False})

        for attempt in attempts:
            try:
                local_only = bool(attempt["local_files_only"])
                use_fp16_variant = bool(attempt["use_variant_fp16"])

                kwargs = dict(
                    torch_dtype=dtype,
                    cache_dir=cache_dir,
                    local_files_only=local_only,
                )
                if use_fp16_variant:
                    kwargs["variant"] = "fp16"

                pipe = AutoPipelineForText2Image.from_pretrained(model_id, **kwargs)
                pipe.set_progress_bar_config(disable=True)

                # Disable safety checker to avoid extra weights and latency for a fully local app.
                try:
                    if hasattr(pipe, "safety_checker"):
                        pipe.safety_checker = None
                    if hasattr(pipe, "requires_safety_checker"):
                        pipe.requires_safety_checker = False
                except Exception:
                    pass

                pipe = pipe.to(device)
                # NOTE: `enable_attention_slicing()` + MPS + float16 can yield NaNs / black images
                # with some pipelines. Skip it on MPS; rely on smaller defaults and CPU fallback.
                if device != "mps":
                    try:
                        pipe.enable_attention_slicing()
                    except Exception:
                        pass
                else:
                    try:
                        # These reduce memory without triggering the MPS attention slicing issue.
                        vae = getattr(pipe, "vae", None)
                        if vae is not None and hasattr(vae, "enable_slicing"):
                            vae.enable_slicing()
                        elif hasattr(pipe, "enable_vae_slicing"):
                            pipe.enable_vae_slicing()

                        if vae is not None and hasattr(vae, "enable_tiling"):
                            vae.enable_tiling()
                        elif hasattr(pipe, "enable_vae_tiling"):
                            pipe.enable_vae_tiling()
                    except Exception:
                        pass
                self._pipe = pipe
                self._device = device
                self._dtype = dtype
                return
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Failed to load SD pipeline for {model_id}: {last_err}")

    def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        steps: int,
        width: int,
        height: int,
        seed: Optional[int] = None,
        on_progress: Optional[ProgressCb] = None,
    ) -> ImageGenResult:
        self._ensure_pipe()
        import torch

        assert self._pipe is not None
        device = str(self._device or "cpu")

        if seed is None:
            seed = random.randint(0, 2**31 - 1)

        def _progress(step_idx: int, total: int) -> None:
            if on_progress is None:
                return
            try:
                on_progress(step_idx, total)
            except Exception:
                pass

        # Diffusers callback APIs vary; implement both best-effort.
        total_steps = max(1, int(steps))

        def callback_on_step_end(*args, **kwargs):
            # Common signatures:
            # (pipeline, step_index, timestep, callback_kwargs)
            try:
                step_index = int(args[1]) if len(args) > 1 else int(kwargs.get("step_index", 0))
            except Exception:
                step_index = 0
            _progress(step_index + 1, total_steps)
            # return callback_kwargs if present
            if len(args) >= 4:
                return args[3]
            return kwargs.get("callback_kwargs")

        # On MPS, using an MPS generator can produce NaNs / black images in some pipelines.
        # Generate noise with a CPU generator and let diffusers move tensors to MPS.
        gen_device = "cpu" if device == "mps" else device
        gen = torch.Generator(device=gen_device).manual_seed(int(seed))

        # SD Turbo models often work best with low guidance.
        guidance_scale = 0.0

        # Be defensive: pipelines vary in accepted kwargs across model types / diffusers versions.
        import inspect

        params = {}
        try:
            params = dict(inspect.signature(self._pipe.__call__).parameters)
        except Exception:
            params = {}

        kwargs = {}
        kwargs["prompt"] = prompt
        if negative_prompt and ("negative_prompt" in params or not params):
            kwargs["negative_prompt"] = negative_prompt
        if "num_inference_steps" in params or not params:
            kwargs["num_inference_steps"] = total_steps
        if "guidance_scale" in params or not params:
            kwargs["guidance_scale"] = guidance_scale
        if ("width" in params or not params) and width:
            kwargs["width"] = int(width)
        if ("height" in params or not params) and height:
            kwargs["height"] = int(height)
        if "generator" in params or not params:
            kwargs["generator"] = gen

        # Progress callbacks
        if "callback_on_step_end" in params:
            kwargs["callback_on_step_end"] = callback_on_step_end
        elif "callback" in params:
            kwargs["callback"] = lambda i, t, latents: _progress(i + 1, total_steps)
            if "callback_steps" in params:
                kwargs["callback_steps"] = 1

        try:
            result = self._pipe(**kwargs)
        except RuntimeError as e:
            # Device OOM fallback.
            if "out of memory" in str(e).lower() and device in ("cuda", "mps"):
                try:
                    self._pipe = self._pipe.to("cpu")
                    self._device = "cpu"
                    return self.generate(
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        steps=steps,
                        width=width,
                        height=height,
                        seed=seed,
                        on_progress=on_progress,
                    )
                except Exception:
                    raise
            raise

        image = result.images[0]
        return ImageGenResult(image=image, seed=int(seed), device=device)

    @property
    def device(self) -> str:
        # Don't force model load just to report the planned device.
        if self._pipe is None:
            return self._select_device()
        return str(self._device or "cpu")
