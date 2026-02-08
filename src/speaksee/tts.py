from __future__ import annotations

import os
import threading


def speak_async(text: str) -> None:
    if os.getenv("SPEAKSEE_TTS", "").strip() not in ("1", "true", "yes", "on"):
        return
    try:
        import pyttsx3  # type: ignore
    except Exception:
        return

    def _run() -> None:
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()

