# Speak \u2192 See

Fully local speech-to-image desktop web app: talk into your microphone, see a generated image immediately. No logins, no telemetry, no cloud inference.

## Hardware Requirements

Recommended:
- Apple Silicon with 16GB+ RAM (MPS acceleration if available in PyTorch), or
- NVIDIA GPU with 8GB+ VRAM (CUDA), or
- CPU-only works but is slow.

Disk:
- Expect **~10\u201320 GB free** for model weights and cache on first use.

## One-Command Startup

```bash
bash ./run.sh
```

First run will:
- Install `uv` if missing
- Create `.venv`
- Install Python dependencies
- Start the local server
- Open the UI in your browser

Mic permission is the only browser permission prompt.

When the page opens, it will request microphone access and then you can **just start speaking** (Auto listen is on by default).

## How It Works (Local Only)
- Speech-to-text runs locally using Whisper via `faster-whisper` (default: `Systran/faster-whisper-base`)
- Image generation runs locally using Stable Diffusion via `diffusers` (default: `stabilityai/sd-turbo`)
- Model weights download automatically if not present (to `data/hf/`)

## Keyboard Shortcuts
- `Space`: talk (tap toggles; hold for hold-to-talk)
- `Enter`: generate (from prompt box)
- `R`: regenerate
- `S`: save image (copies to `data/saved/`)
- `Esc`: stop recording / cancel auto-generate countdown

UI:
- **Auto listen** (top bar): when enabled, recording starts/stops automatically when you speak.

## Voice Commands
Speak any of these as standalone commands:
- `regenerate`
- `more realistic`
- `more abstract`
- `save image`

## Switching Models Later

Set environment variables before running:

```bash
SPEAKSEE_SD_MODEL="runwayml/stable-diffusion-v1-5" \
SPEAKSEE_WHISPER_MODEL="Systran/faster-whisper-small" \
bash ./run.sh
```

Notes:
- Some Hugging Face models are gated and may require accepting a license; the defaults are chosen to be ungated (no login).

Useful overrides:
- `SPEAKSEE_STEPS=4`
- `SPEAKSEE_DEVICE=cpu|mps|cuda`
- `SPEAKSEE_PORT=7860`

## Troubleshooting

### Microphone Permission Denied
- Allow microphone access for your browser to `http://127.0.0.1:7860`.

### Slow Performance
- CPU-only generation can be very slow.
- Reduce steps: `SPEAKSEE_STEPS=2`

### MPS/CUDA Not Available
- The app falls back to CPU automatically.
- On macOS, ensure you have a recent PyTorch build with MPS support.

### Out Of Memory
- The generator will retry on CPU if the selected device runs out of memory.

### Logs
- Server logs are written to `data/logs/server.log`.

## Manual Acceptance Test
1. Start the app: `bash ./run.sh`
2. Open the page and say: `a lighthouse on a cliff at sunrise` (Auto listen is on by default)
3. Confirm the **Live transcript** updates while speaking.
4. Stop speaking and wait for **Auto-generate** (or press **Generate**).
5. Confirm an image appears and the Gallery populates.
6. Say `more realistic` and confirm a new image is generated.
7. Say `save image` (or press `S`) and confirm a file appears in `data/saved/`.
8. Refresh the page and confirm the gallery persists.
