from __future__ import annotations

import asyncio
import json
import os
import random
import traceback
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .commands import parse_voice_command
from .config import Config, load_config
from .gallery import copy_to_saved, list_gallery, save_generated_image
from .image_sd import ImageGenerator
from .session import SessionState
from .stt_whisper import SpeechToText
from .tts import speak_async
from .ws_protocol import dumps, error, status


def _set_privacy_env_defaults(cfg: Config) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HOME", str(cfg.hf_home))


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="Speak → See", docs_url=None, redoc_url=None)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/images", StaticFiles(directory=str(cfg.gallery_dir)), name="images")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/api/gallery")
    async def api_gallery() -> JSONResponse:
        return JSONResponse({"items": list_gallery(cfg)})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await handle_ws(cfg, ws)

    return app


async def _ws_send(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(dumps(payload))


def _slice_last_seconds(pcm16: bytearray, sample_rate: int, seconds: float) -> bytes:
    if sample_rate <= 0:
        return bytes(pcm16)
    bytes_per_sample = 2  # int16 mono
    max_samples = int(sample_rate * seconds)
    max_bytes = max_samples * bytes_per_sample
    if len(pcm16) <= max_bytes:
        return bytes(pcm16)
    return bytes(pcm16[-max_bytes:])


async def handle_ws(cfg: Config, ws: WebSocket) -> None:
    await ws.accept()
    loop = asyncio.get_running_loop()

    stt = SpeechToText(cfg)
    gen = ImageGenerator(cfg)
    state = SessionState()

    partial_task: Optional[asyncio.Task[None]] = None

    async def send_models() -> None:
        await _ws_send(
            ws,
            {
                "type": "models",
                "stt_model": cfg.whisper_model,
                "image_model": cfg.sd_model,
                "device": gen.device,
            },
        )

    async def start_partial_loop() -> None:
        nonlocal partial_task

        async def _loop() -> None:
            last_sent = ""
            while state.recording:
                await asyncio.sleep(cfg.stt_partial_interval_s)
                if not state.recording:
                    break
                if state.transcription_lock.locked():
                    continue
                pcm = _slice_last_seconds(
                    state.audio_pcm16, state.sample_rate, cfg.stt_partial_window_s
                )
                if len(pcm) < 32000:  # < 1s at 16k
                    continue
                try:
                    async with state.transcription_lock:
                        res = await asyncio.to_thread(stt.transcribe_partial, pcm, state.sample_rate)
                    text = res.text
                    if text and text != last_sent:
                        last_sent = text
                        await _ws_send(ws, {"type": "transcript_partial", "text": text})
                except Exception:
                    # Partial is best-effort; never kill the session.
                    continue

        partial_task = asyncio.create_task(_loop())

    async def stop_partial_loop() -> None:
        nonlocal partial_task
        if partial_task is None:
            return
        # Don't cancel mid-transcribe (thread can't be interrupted). Let it exit naturally.
        try:
            await asyncio.wait_for(partial_task, timeout=2.0)
        except Exception:
            pass
        partial_task = None

    async def do_generate(prompt: str) -> None:
        prompt = (prompt or "").strip()
        if not prompt:
            await _ws_send(ws, error("Empty prompt."))
            return

        if state.generation_lock.locked():
            await _ws_send(ws, error("Already generating. Please wait."))
            return

        token = state.bump_generation_token()

        style = state.style
        negative = ""
        full_prompt = prompt
        if style == "realistic":
            full_prompt = f"{prompt}, {cfg.realistic_prompt_suffix}"
            negative = cfg.realistic_negative
        elif style == "abstract":
            full_prompt = f"{prompt}, {cfg.abstract_prompt_suffix}"
            negative = cfg.abstract_negative

        state.last_prompt = prompt
        state.last_negative_prompt = negative

        steps = max(1, int(cfg.steps))
        seed = random.randint(0, 2**31 - 1)

        await _ws_send(ws, status("generating", "Generating image..."))
        await _ws_send(ws, {"type": "gen_started", "prompt": prompt, "seed": seed, "steps": steps})

        def on_progress(step_i: int, total: int) -> None:
            if token != state.generation_token:
                return
            pct = int((step_i / max(1, total)) * 100)
            try:
                asyncio.run_coroutine_threadsafe(
                    _ws_send(
                        ws,
                        {
                            "type": "gen_progress",
                            "step": int(step_i),
                            "total_steps": int(total),
                            "percent": pct,
                        },
                    ),
                    loop,
                )
            except Exception:
                pass

        try:
            async with state.generation_lock:
                result = await asyncio.to_thread(
                    gen.generate,
                    prompt=full_prompt,
                    negative_prompt=negative,
                    steps=steps,
                    width=cfg.width,
                    height=cfg.height,
                    seed=seed,
                    on_progress=on_progress,
                )
        except Exception as e:
            await _ws_send(ws, error("Image generation failed.", str(e)))
            await _ws_send(ws, status("ready", ""))
            return

        if token != state.generation_token:
            # superseded; discard
            await _ws_send(ws, status("ready", ""))
            return

        meta = save_generated_image(
            cfg,
            result.image,
            prompt=prompt,
            negative_prompt=negative,
            seed=result.seed,
            steps=steps,
            style=style,
            model_id=cfg.sd_model,
            device=result.device,
        )
        state.last_image_id = meta["id"]

        await _ws_send(
            ws,
            {
                "type": "gen_result",
                "id": meta["id"],
                "url": f"/images/{meta['file']}",
                "prompt": meta["prompt"],
                "seed": meta["seed"],
                "style": meta["style"],
                "ts": meta["ts"],
            },
        )
        await _ws_send(ws, {"type": "gallery", "items": list_gallery(cfg)})
        await _ws_send(ws, status("ready", ""))

    async def do_regenerate() -> None:
        if not state.last_prompt:
            await _ws_send(ws, error("No previous prompt to regenerate."))
            return
        await do_generate(state.last_prompt)

    async def do_save_image() -> None:
        if not state.last_image_id:
            await _ws_send(ws, error("No image to save yet."))
            return
        try:
            await _ws_send(ws, status("saving", "Saving image..."))
            path = await asyncio.to_thread(copy_to_saved, cfg, state.last_image_id)
            await _ws_send(ws, {"type": "saved", "id": state.last_image_id, "path": str(path)})
            await _ws_send(ws, status("ready", "Saved."))
            speak_async("Saved")
        except Exception as e:
            await _ws_send(ws, error("Save failed.", str(e)))
            await _ws_send(ws, status("ready", ""))

    await _ws_send(ws, status("idle", ""))
    await send_models()
    await _ws_send(ws, {"type": "gallery", "items": list_gallery(cfg)})

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if "bytes" in msg and msg["bytes"] is not None:
                if state.recording:
                    state.audio_pcm16.extend(msg["bytes"])
                continue

            text = msg.get("text")
            if not text:
                continue
            try:
                data = json.loads(text)
            except Exception:
                await _ws_send(ws, error("Invalid JSON message."))
                continue

            mtype = data.get("type")

            if mtype == "hello":
                await send_models()
                continue

            if mtype == "audio_start":
                state.audio_pcm16 = bytearray()
                state.sample_rate = int(data.get("sample_rate") or 16000)
                state.recording = True
                await _ws_send(ws, status("recording", "Listening..."))
                await start_partial_loop()
                continue

            if mtype == "audio_stop":
                if not state.recording:
                    continue
                state.recording = False
                await stop_partial_loop()
                await _ws_send(ws, status("transcribing", "Transcribing..."))

                pcm = bytes(state.audio_pcm16)
                state.audio_pcm16 = bytearray()

                try:
                    async with state.transcription_lock:
                        res = await asyncio.to_thread(stt.transcribe_final, pcm, state.sample_rate)
                except Exception as e:
                    await _ws_send(ws, error("Transcription failed.", str(e)))
                    await _ws_send(ws, status("ready", ""))
                    continue

                final_text = res.text
                await _ws_send(ws, {"type": "transcript_final", "text": final_text})

                cmd = parse_voice_command(final_text)
                if cmd is None:
                    await _ws_send(ws, status("ready", ""))
                    continue

                # Execute voice commands immediately (client will also suppress autogen).
                if cmd.name == "save_image":
                    await do_save_image()
                    continue
                if cmd.name == "regenerate":
                    await do_regenerate()
                    continue
                if cmd.name == "more_realistic":
                    state.style = "realistic"
                    await do_regenerate()
                    continue
                if cmd.name == "more_abstract":
                    state.style = "abstract"
                    await do_regenerate()
                    continue

                await _ws_send(ws, status("ready", ""))
                continue

            if mtype == "generate":
                prompt = str(data.get("prompt") or "")
                await do_generate(prompt)
                continue

            if mtype == "action":
                name = str(data.get("name") or "")
                if name == "regenerate":
                    await do_regenerate()
                    continue
                if name == "save_image":
                    await do_save_image()
                    continue
                if name == "set_style":
                    val = str(data.get("value") or "none").lower()
                    if val in ("none", "realistic", "abstract"):
                        state.style = val
                        await _ws_send(ws, status("ready", f"Style: {val}"))
                    else:
                        await _ws_send(ws, error("Unknown style.", val))
                    continue
                await _ws_send(ws, error("Unknown action.", name))
                continue

            await _ws_send(ws, error("Unknown message type.", str(mtype)))

    except WebSocketDisconnect:
        pass
    finally:
        state.recording = False
        await stop_partial_loop()


def main() -> None:
    cfg = load_config()
    _set_privacy_env_defaults(cfg)

    import uvicorn

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
